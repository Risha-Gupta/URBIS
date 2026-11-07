from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class BuildingSummary(_Base):
    building_id: str
    dataset_id: str
    half: str | None = None
    coverage_class: str | None = None
    num_points: int | None = None
    footprint_area_m2: float | None = None
    footprint_source: str | None = Field(None, description="`lidar_hull` = convex hull of roof points (overestimates L-shaped roofs).")
    lon: float | None = None
    lat: float | None = None
    recon_id: int | None = None
    version: int | None = None
    status: str | None = None
    n_pred_corners: int | None = None
    n_pred_edges: int | None = None
    has_model: bool = False
    created_at: datetime | None = Field(None, description="Seed export time, not a real processing time (until Phase 8).")
    model_confidence: float | None = None
    combined_confidence: float | None = None
    confidence_class: str | None = None
    action: str | None = None
    decision_policy: str | None = None
    total_roof_area_m2: float | None = None
    usable_roof_area_m2: float | None = None
    annual_kwh: float | None = None
    annual_kwh_unshaded: float | None = None
    shading_loss_frac: float | None = None
    kwh_per_m2_roof: float | None = None
    dominant_tilt_deg: float | None = None
    dominant_azimuth_deg: float | None = None
    solar_reliability: str | None = None
    p_bad: float | None = None
    review_rank: int | None = None
    solar_review: bool | None = None


class NearProps(BuildingSummary):
    distance_m: float


class Feature(_Base):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: dict[str, Any] | None
    properties: dict[str, Any]


class FeatureCollection(_Base):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    numberMatched: int
    numberReturned: int
    limit: int
    offset: int
    features: list[Feature]


class BuildingPage(_Base):
    total: int
    limit: int
    offset: int
    items: list[BuildingSummary]


class RoofRankRow(BuildingSummary):
    rank: int
    metric: str
    metric_value: float | None = None


class RoofRanking(_Base):
    metric: str
    reliability_filter: list[str] | None = Field(
        None, description="None means every reliability tier is included.")
    total: int
    limit: int
    offset: int
    items: list[RoofRankRow]


class Plane(_Base):
    plane_id: int
    tilt_deg: float | None = None
    azimuth_deg: float | None = None
    area_m2: float | None = None
    n_points: int | None = None
    rms_m: float | None = None
    lon: float | None = None
    lat: float | None = None
    mean_z: float | None = None
    is_flat: bool | None = None
    viable: bool | None = None
    panel_tilt_deg: float | None = None
    panel_azimuth_deg: float | None = None
    usable_area_m2: float | None = None
    irradiation_kwh_m2: float | None = None
    annual_kwh: float | None = None
    annual_kwh_unshaded: float | None = None
    shading_loss_frac: float | None = None
    horizon_max_deg: float | None = None
    sky_view_factor: float | None = None


class BuildingDetail(_Base):
    building: BuildingSummary
    uncertainty: dict[str, Any] | None
    footprint: dict[str, Any] | None
    n_planes: int
    links: dict[str, str]


class CountMap(_Base):
    counts: dict[str, int]


class YieldAtRisk(_Base):
    basis: str
    n_buildings: int
    total_gwh: float
    bad_share_of_buildings: float
    gwh_in_bad_buildings: float
    share_in_bad_accept_all: float
    gwh_in_accepted_bad_buildings: float
    share_in_accepted_bad_rule: float


class Summary(_Base):
    scope: str
    n_buildings: int
    by_action: dict[str, int]
    by_status: dict[str, int]
    by_solar_reliability: dict[str, int]
    by_coverage_class: dict[str, int]
    escalate_rate: float
    policy: dict[str, Any]
    total_gwh_shaded: float
    total_gwh_unshaded: float
    gwh_by_action: dict[str, float]
    yield_at_risk: YieldAtRisk | None
    caveats: list[str]
