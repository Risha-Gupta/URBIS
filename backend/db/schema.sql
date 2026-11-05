-- URBIS Phase 7: geospatial schema (PostgreSQL 16 + PostGIS 3.4)
-- Storage CRS: EPSG:3301 (Estonian L-EST97, metres). WGS84 copies are generated for web maps.
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE datasets (
    dataset_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    source      TEXT,
    crs         TEXT,
    notes       TEXT
);

CREATE TABLE buildings (
    building_id       TEXT PRIMARY KEY,
    dataset_id        TEXT NOT NULL REFERENCES datasets,
    split             TEXT NOT NULL,
    half              TEXT CHECK (half IN ('tune', 'hold')),       -- Phase 4 tuning / held-out half
    coverage_class    TEXT CHECK (coverage_class IN ('dense', 'sparse')),
    num_points        INTEGER,
    footprint         geometry(Polygon, 3301) NOT NULL,
    footprint_source  TEXT NOT NULL,                               -- 'lidar_hull' (convex hull of the cached roof points)
    footprint_area_m2 DOUBLE PRECISION,
    z_min             DOUBLE PRECISION,
    z_max             DOUBLE PRECISION,
    centroid          geometry(Point, 3301)  GENERATED ALWAYS AS (ST_Centroid(footprint)) STORED,
    centroid_wgs84    geometry(Point, 4326)  GENERATED ALWAYS AS (ST_Transform(ST_Centroid(footprint), 4326)) STORED
);

-- One row per reconstruction attempt (version 1 = Phase 2/3 result; retries arrive in Phase 8).
CREATE TABLE reconstructions (
    recon_id         BIGSERIAL PRIMARY KEY,
    building_id      TEXT NOT NULL REFERENCES buildings ON DELETE CASCADE,
    version          INTEGER NOT NULL DEFAULT 1,
    status           TEXT NOT NULL CHECK (status IN ('completed', 'failed_zero_corners', 'failed_no_roof_planes')),
    n_pred_corners   INTEGER,
    n_pred_edges     INTEGER,
    model_path       TEXT,                                          -- NULL until a mesh/GLB exists
    pipeline_version TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (building_id, version)
);

CREATE TABLE uncertainty (
    recon_id                      BIGINT PRIMARY KEY REFERENCES reconstructions ON DELETE CASCADE,
    mean_corner_spread_m          DOUBLE PRECISION,
    max_corner_spread_m           DOUBLE PRECISION,
    corner_confidence             DOUBLE PRECISION,
    mean_edge_entropy             DOUBLE PRECISION,
    edge_confidence               DOUBLE PRECISION,
    model_confidence              DOUBLE PRECISION,
    osm_available                 BOOLEAN,
    osm_centroid_distance_m       DOUBLE PRECISION,
    osm_iou                       DOUBLE PRECISION,
    osm_area_error                DOUBLE PRECISION,
    microsoft_available           BOOLEAN,
    microsoft_centroid_distance_m DOUBLE PRECISION,
    microsoft_iou                 DOUBLE PRECISION,
    microsoft_area_error          DOUBLE PRECISION,
    external_confidence           DOUBLE PRECISION,
    combined_confidence           DOUBLE PRECISION,
    confidence_class              TEXT
);

-- Triage decisions per policy version; exactly one row per reconstruction is current.
CREATE TABLE decisions (
    decision_id     BIGSERIAL PRIMARY KEY,
    recon_id        BIGINT NOT NULL REFERENCES reconstructions ON DELETE CASCADE,
    policy_version  TEXT NOT NULL,
    action          TEXT NOT NULL CHECK (action IN ('ACCEPT', 'ACCEPT_FLAG', 'ESCALATE')),
    confidence_used DOUBLE PRECISION,
    t_low           DOUBLE PRECISION,
    t_acc           DOUBLE PRECISION,
    is_current      BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (recon_id, policy_version)
);
CREATE UNIQUE INDEX one_current_decision ON decisions (recon_id) WHERE is_current;

-- Ground-truth based scores: for reports and validation only, NOT exposed by the public API.
CREATE TABLE evaluation (
    building_id       TEXT PRIMARY KEY REFERENCES buildings ON DELETE CASCADE,
    half              TEXT,
    min_f1_1m         DOUBLE PRECISION,
    is_bad            SMALLINT,
    min_f1_phase4_old DOUBLE PRECISION,
    is_bad_phase4_old SMALLINT
);

CREATE TABLE solar_buildings (
    building_id            TEXT PRIMARY KEY REFERENCES buildings ON DELETE CASCADE,
    n_planes               INTEGER,
    plane_point_coverage   DOUBLE PRECISION,
    total_roof_area_m2     DOUBLE PRECISION,
    usable_roof_area_m2    DOUBLE PRECISION,
    annual_kwh             DOUBLE PRECISION,
    annual_kwh_unshaded    DOUBLE PRECISION,
    shading_loss_frac      DOUBLE PRECISION,
    kwh_per_m2_roof        DOUBLE PRECISION,
    dominant_tilt_deg      DOUBLE PRECISION,
    dominant_azimuth_deg   DOUBLE PRECISION,
    dominant_is_flat       BOOLEAN,
    projected_roof_area_m2 DOUBLE PRECISION,
    gt_corner_hull_area_m2 DOUBLE PRECISION,
    projected_vs_gt_hull_ratio DOUBLE PRECISION,
    area_outlier           BOOLEAN,
    solar_reliability      TEXT CHECK (solar_reliability IN
        ('ok', 'estimate_flagged', 'estimate_escalated', 'area_outlier', 'low_plane_coverage', 'no_roof_planes')),
    solar_rank             DOUBLE PRECISION,
    p_bad                  DOUBLE PRECISION,
    p_bad_out_of_sample    BOOLEAN,
    review_priority        DOUBLE PRECISION,
    review_rank            INTEGER,
    solar_review           BOOLEAN,
    policy_version         TEXT
);

CREATE TABLE roof_planes (
    building_id         TEXT NOT NULL REFERENCES buildings ON DELETE CASCADE,
    plane_id            INTEGER NOT NULL,
    tilt_deg            DOUBLE PRECISION,
    azimuth_deg         DOUBLE PRECISION,
    area_m2             DOUBLE PRECISION,
    n_points            INTEGER,
    rms_m               DOUBLE PRECISION,
    cx                  DOUBLE PRECISION,
    cy                  DOUBLE PRECISION,
    mean_z              DOUBLE PRECISION,
    ground_like         BOOLEAN,
    is_flat             BOOLEAN,
    viable              BOOLEAN,
    panel_tilt_deg      DOUBLE PRECISION,
    panel_azimuth_deg   DOUBLE PRECISION,
    usable_area_m2      DOUBLE PRECISION,
    irradiation_kwh_m2  DOUBLE PRECISION,
    annual_kwh          DOUBLE PRECISION,
    annual_kwh_unshaded DOUBLE PRECISION,
    shading_loss_frac   DOUBLE PRECISION,
    horizon_max_deg     DOUBLE PRECISION,
    sky_view_factor     DOUBLE PRECISION,
    centroid            geometry(Point, 3301) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(cx, cy), 3301)) STORED,
    PRIMARY KEY (building_id, plane_id)
);

-- City3D robustness run (out-of-distribution, no coordinates).
CREATE TABLE robustness_scores (
    building_id           TEXT PRIMARY KEY,
    dataset_id            TEXT NOT NULL REFERENCES datasets,
    subset                TEXT,
    coverage_class        TEXT,
    num_points            INTEGER,
    num_predicted_corners INTEGER,
    model_confidence      DOUBLE PRECISION,
    min_f1_1m             DOUBLE PRECISION,
    action                TEXT,
    is_bad                SMALLINT
);

-- Indexes
CREATE INDEX buildings_footprint_gix    ON buildings USING GIST (footprint);
CREATE INDEX buildings_centroid_gix     ON buildings USING GIST (centroid);
CREATE INDEX buildings_centroid4326_gix ON buildings USING GIST (centroid_wgs84);
CREATE INDEX roof_planes_centroid_gix   ON roof_planes USING GIST (centroid);
CREATE INDEX reconstructions_status_ix  ON reconstructions (status);
CREATE INDEX uncertainty_conf_ix        ON uncertainty (model_confidence);
CREATE INDEX decisions_current_action_ix ON decisions (action) WHERE is_current;
CREATE INDEX solar_kwh_ix               ON solar_buildings (annual_kwh DESC);
CREATE INDEX solar_reliability_ix       ON solar_buildings (solar_reliability);
CREATE INDEX solar_review_rank_ix       ON solar_buildings (review_rank);

-- Latest reconstruction + current decision + uncertainty + solar: the API reads from this view.
CREATE VIEW v_building_summary AS
SELECT b.building_id, b.dataset_id, b.half, b.coverage_class, b.num_points,
       b.footprint, b.centroid, b.centroid_wgs84, b.footprint_area_m2, b.footprint_source,
       r.recon_id, r.version, r.status, r.n_pred_corners, r.n_pred_edges, r.model_path, r.created_at,
       u.model_confidence, u.corner_confidence, u.edge_confidence, u.combined_confidence, u.confidence_class,
       d.action, d.policy_version AS decision_policy,
       s.total_roof_area_m2, s.usable_roof_area_m2, s.annual_kwh, s.annual_kwh_unshaded, s.shading_loss_frac,
       s.kwh_per_m2_roof, s.dominant_tilt_deg, s.dominant_azimuth_deg, s.dominant_is_flat,
       s.solar_reliability, s.p_bad, s.review_rank, s.solar_review
FROM buildings b
JOIN LATERAL (SELECT * FROM reconstructions rr WHERE rr.building_id = b.building_id
              ORDER BY rr.version DESC LIMIT 1) r ON TRUE
LEFT JOIN uncertainty u     ON u.recon_id = r.recon_id
LEFT JOIN decisions d       ON d.recon_id = r.recon_id AND d.is_current
LEFT JOIN solar_buildings s ON s.building_id = b.building_id;
