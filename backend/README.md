# URBIS Phase 7 - Geospatial backend

## Run
```bash
# layout: db/schema.sql, seed/*.csv + manifest.json (+ city3d_scores_with_actions.csv), etl/{load_seed.py,requirements.txt,Dockerfile}
docker compose up -d db
docker compose --profile etl run --rm etl      # loads 3,207 buildings / 9,116 planes, verifies, rolls back on failure
docker compose up -d --build backend           # http://localhost:8000/docs
```
Optional: put GLB/OBJ files in `./models` and set `reconstructions.model_path` relative to it.

## Test
```bash
pip install -r requirements-dev.txt
pytest tests/test_filters.py tests/test_validation.py     # no database needed
DATABASE_URL=postgresql://urbis:urbis@localhost:5432/urbis pytest   # full acceptance checks
```

## Endpoints
| Endpoint | Purpose |
|---|---|
| GET /buildings/within | Bounding box; POST takes a GeoJSON Polygon/MultiPolygon |
| GET /buildings/near | Radius in metres, nearest first, `distance_m` per feature |
| GET /buildings | Filter/sort: action, status (`failed` alias), confidence range, reliability, coverage, half |
| GET /rankings/roofs | metric = annual_kwh / kwh_per_m2_roof / usable_roof_area_m2; `ok` roofs only by default |
| GET /stats/summary | Counts, GWh, yield at risk (aggregate), `?half=hold` for reportable numbers |
| GET /buildings/{id}, /planes, /model | Detail, roof planes, model download (404 until a model exists) |
| GET /robustness/summary, /datasets, /health, /ready | Meta |

## Design notes
- EPSG:3301 stored; query geometry is transformed to 3301 (never the column) so GiST indexes are used. Distances are in metres.
- Plain SQL via psycopg; all values bound parameters; ORDER BY columns come from whitelists.
- Ground-truth `evaluation` rows are only used for the aggregate yield-at-risk figure.
- `footprint_source = lidar_hull`: convex hulls overstate L-shaped roofs. `created_at` is the seed export time.
