# URBIS – Urban Intelligence and Self-Correction

**URBIS turns airborne LiDAR point clouds of Tallinn into 3D building models, tells you how far to trust each one, and routes the doubtful ones to a human reviewer.** On top of the reconstructions it estimates rooftop solar potential per building and serves everything through a spatial API and a web platform with a 3D city explorer.

It is a final-year major project built on the [Building3D](https://building3d.ucalgary.ca/) Tallinn dataset (3,207 test-split buildings).

---

## What it does

1. **Reconstructs** each building's roof from a LiDAR point cloud (corner detection + edge prediction).
2. **Scores confidence** from the model's own uncertainty plus agreement with external footprints (OpenStreetMap and Microsoft Global ML Building Footprints).
3. **Decides** per building: accept, accept with a flag, or escalate to human review.
4. **Estimates solar potential** from roof planes fitted to the raw points, with PVGIS irradiation and neighbour shading.
5. **Serves** all of it through a FastAPI + PostGIS backend and a React/Cesium web platform with a job and review workflow.

---

## Platform tour

### Dashboard
<img src="screenshots_urbis/Screenshot%202026-11-11%20002912.png" width="900">

Dashboard: Overview of building reconstructions, confidence scores, solar potential, and pending reviews.

<img src="screenshots_urbis/Screenshot%202026-11-11%20002926.png" width="900">

Dashboard Overview: Monitor recent reconstruction jobs, building statistics, and backend status.


### City Explorer and 3D viewer
<img src="screenshots_urbis/Screenshot%202026-11-11%20002941.png" width="900">

City Explorer: Explore reconstructed buildings on an interactive map and locate individual assets.

<img src="screenshots_urbis/Screenshot%202026-11-11%20003116.png" width="900">

3D Building Viewer: Inspect individual 3D buildings alongside their reconstruction confidence and solar estimates.


### Building registry
<img src="screenshots_urbis/Screenshot%202026-11-11%20003208.png" width="900">

Building Registry: Browse buildings and compare their reconstruction status, confidence, and solar estimates.


### Processing jobs and review
<img src="screenshots_urbis/Screenshot%202026-11-11%20003244.png" width="900">

Processing Jobs: Submit LiDAR point clouds and track reconstruction job progress.

<img src="screenshots_urbis/Screenshot%202026-11-11%20003307.png" width="900">

Review Workspace: Find completed reconstructions awaiting human review and approval.

<img src="screenshots_urbis/Screenshot%202026-11-11%20003325.png" width="900">

Reconstruction History: Compare reconstruction versions and inspect confidence scores and correction results.

<img src="screenshots_urbis/Screenshot%202026-11-11%20003336.png" width="900">

Review & Approval: Approve or reject reconstructed buildings, add notes, and leave review comments.


### Analytics
<img src="screenshots_urbis/Screenshot%202026-11-11%20003437.png" width="900">

Analytics: View city-wide reconstruction statistics, decision distributions, and estimated solar generation.

<img src="screenshots_urbis/Screenshot%202026-11-11%20003448.png" width="900">

Model Analytics: Explore reconstruction reliability, building coverage, and data quality insights.

---

## How it works

| Phase | What was built |
|---|---|
| 1 | Building3D Tallinn acquisition, pairing of point clouds, wireframes and meshes, and a deterministic 80/10/10 split. |
| 2 | **CornerPointNet2** (per-point corner probability and offsets) and **EdgeGraphNet** (scores every corner pair), trained for 20 epochs each on 2,048-point clouds. |
| 3 | Uncertainty: 8 perturbation passes for corners (jitter and point dropout), MC Dropout for edges, then a cross-check against OSM and Microsoft footprints. Combined confidence is 0.5 × model confidence + 0.5 × external agreement. A missing external source is never counted as disagreement. |
| 4 | Triage layer that accepts, flags or escalates each building. Retries were tested and dropped because they did not pay for themselves. |
| 5 | Solar: sequential RANSAC roof planes from the raw points, PVGIS irradiation by tilt and azimuth, horizon-based neighbour shading, reliability tiers and a value-aware review queue. |
| 6 | Held-out evaluation, calibration, policy comparison and a City3D robustness check. Triage thresholds were re-based (escalate below 0.7165, accept at 0.7393 or above). |
| 7 | FastAPI backend on PostgreSQL/PostGIS with spatial search, filtering, rankings and statistics. |
| 8 | Job and review workflow: LiDAR upload, live progress over Server-Sent Events, versioned results, retries, approve/reject/comment. |
| 9 | React + Cesium City Explorer that loads each building's GLB model on selection. |

### Headline results (Tallinn held-out, n = 1,604)

| Metric | Value |
|---|---|
| Corner precision / recall / F1 (1.0 m tolerance) | 0.733 / 0.767 / 0.749 |
| Edge precision / recall / F1 | 0.346 / 0.536 / 0.420 |
| Mean min-F1 | 0.575 |
| Confidence vs min-F1 (Spearman) | 0.544 |
| AUC for flagging bad buildings | 0.769 |
| Calibration error (ECE vs corner recall) | 0.060 |
| Bad rate among accepted buildings | 18.0% → 10.2% with the triage rule (29.5% review rate) |
| Solar coverage | 3,201 of 3,207 buildings, 9,116 roof planes, about 42.6 GWh/year |

### Honest limitations

- Edges are the weak part of the model (edge F1 0.420 against corner F1 0.749).
- Under the assumed costs, reviewing costs more than the misses it prevents (0.438 against 0.360 for accept-all). The cost weights were assumed, not measured.
- On City3D (a different region, with denser reference meshes) confidence drops sharply. Treat it as an out-of-distribution test, not an accuracy figure.
- Solar numbers are modelled estimates. They have not been compared with ground-truth solar yields. Shading ignores trees and snow.
- **The 3D models in the viewer are visualisation geometry.** Walls come from a building outline and the roof from the fitted roof planes. They are not the model's predicted wireframe. Predictions, confidence and uncertainty are stored separately.
- The job pipeline in the Phase 8 workflow uses a deterministic stub for its stages, so confidence values from newly submitted jobs do not come from the Phase 2–4 models.

---

## Repository layout

```
backend/              FastAPI app, PostGIS schema, seed loader, tests, Docker setup
frontend/             React + TypeScript + Vite web platform (Cesium for the 3D map)
screenshots_urbis/    Screenshots used in this README
```

---

## Running it

You need **Docker Desktop** and **Node.js 18+**.

### 1. Backend and database

```bash
cd backend
docker compose up -d --build
```

This starts three services: `db` (PostGIS 16, bound to `localhost:5433`), `etl` (loads the seed data in one transaction and checks file hashes, row counts, geometry validity and SRID) and `backend` (uvicorn on port 8000).

- API health: <http://localhost:8000/health>
- Interactive API docs: <http://localhost:8000/docs>

Main endpoints: `/buildings`, `/buildings/{id}`, `/buildings/within`, `/buildings/near`, `/rankings/roofs`, `/stats/summary`, `/jobs`, `/jobs/{id}/events`, `/assets/glb/manifest` and `/assets/glb/{id}.glb`.

> The seed data bundle (building, decision, solar and roof-plane tables) and the GLB models are large and are not stored in git. Place the seed bundle where the `etl` service expects it, and put GLB files in `backend/models/glb/` with `backend/models/glb_manifest.json` next to them.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The app talks to `http://localhost:8000` by default (see `src/services/api/axios.ts`). The map uses OpenStreetMap tiles, so it needs internet access.

### 3. Tests

```bash
cd backend
pytest
```

The backend has automated tests for the spatial API (Phase 7) and the job and review workflow (Phase 8).

---

## Tech stack

Python, PyTorch (PointNet++-style corner network and graph edge network), NumPy/SciPy/Shapely, PVGIS, FastAPI, PostgreSQL + PostGIS, Docker Compose, React, TypeScript, Vite, CesiumJS.

## Data and credits

Point clouds and reference geometry: [Building3D](https://building3d.ucalgary.ca/) (Tallinn). Footprint cross-checks: OpenStreetMap contributors and Microsoft Global ML Building Footprints. Solar irradiation: PVGIS (European Commission JRC).

### 4. Rebuilding the 3D models

`tools/build_lod_glb.py` builds a clean 3D model per building: walls from the building outline (OSM where available, otherwise the hull of the LiDAR roof points) and a flat-faceted roof from the fitted roof planes. It writes GLB files plus a patched manifest, and `--install` copies both into the backend.

```bash
python tools/build_lod_glb.py \
  --npz-dir subset \
  --manifest backend/models/glb_manifest.json \
  --planes phase5_roof_planes.csv \
  --ground-from-manifest \
  --ids 10057 10180 4409 \
  --out lod_glb --install backend/models
docker compose -f backend/docker-compose.yml restart backend
```

Inputs: one `<id>.npz` per building (`points`, `scale`, `center`, exported from the Phase 2 cache) and `phase5_roof_planes.csv` from the Phase 5 solar notebook. Neither is stored in git.
