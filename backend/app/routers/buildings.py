import json
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from .. import db
from ..config import settings
from ..filters import SORT_COLUMNS, SUMMARY_COLS, Filters, Page, SortBy, filters, page, where_sql
from ..schemas import BuildingDetail, BuildingPage, FeatureCollection, Plane

log = logging.getLogger("urbis.buildings")
router = APIRouter(tags=["buildings"])

GEOM_SQL = {
    "footprint": "ST_AsGeoJSON(ST_Transform(v.footprint, 4326), 6)",
    "centroid": "ST_AsGeoJSON(v.centroid_wgs84, 6)",
}
Geometry = Literal["footprint", "centroid"]
Match = Literal["intersects", "centroid"]

POLY_BODY_EXAMPLE = {
    "type": "Polygon",
    "coordinates": [[[24.74, 59.43], [24.77, 59.43], [24.77, 59.445], [24.74, 59.445], [24.74, 59.43]]],
}


def _where(f: Filters, extra: list[str] | None = None) -> tuple[str, dict]:
    clauses, params = where_sql(f)
    clauses = (extra or []) + clauses
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _feature(row: dict) -> dict:
    geom = row.pop("geom", None)
    return {"type": "Feature", "id": row["building_id"],
            "geometry": json.loads(geom) if geom else None, "properties": row}


def _collection(rows: list[dict], total: int, pg: Page) -> dict:
    return {"type": "FeatureCollection", "numberMatched": total, "numberReturned": len(rows),
            "limit": pg.limit, "offset": pg.offset, "features": [_feature(r) for r in rows]}


def _spatial(geom_expr: str, params: dict, f: Filters, pg: Page, geometry: str, match: str) -> dict:
    """geom_expr is a SQL expression yielding a 3301 geometry from bound params."""
    pred = "ST_Intersects(v.footprint, g.g)" if match == "intersects" else "ST_Within(v.centroid, g.g)"
    where, fp = _where(f, [pred])
    params = {**params, **fp, "limit": pg.limit, "offset": pg.offset}
    base = f"FROM v_building_summary v, (SELECT {geom_expr} AS g) g{where}"
    total = db.fetch_one(f"SELECT count(*) AS n {base}", params)["n"]
    rows = db.fetch_all(
        f"SELECT {SUMMARY_COLS}, {GEOM_SQL[geometry]} AS geom {base} "
        f"ORDER BY v.building_id LIMIT %(limit)s OFFSET %(offset)s", params)
    return _collection(rows, total, pg)


@router.get("/buildings/within", response_model=FeatureCollection, summary="Buildings inside a bounding box")
def within_bbox(
    min_lon: float = Query(..., ge=-180, le=180, examples=[24.74]),
    min_lat: float = Query(..., ge=-90, le=90, examples=[59.43]),
    max_lon: float = Query(..., ge=-180, le=180, examples=[24.77]),
    max_lat: float = Query(..., ge=-90, le=90, examples=[59.445]),
    geometry: Geometry = Query("footprint", description="Geometry returned for each feature (WGS84)."),
    match: Match = Query("intersects", description="`intersects` = footprint touches the box; `centroid` = centroid inside."),
    f: Filters = Depends(filters), pg: Page = Depends(page),
):
    """Lon/lat box, converted to EPSG:3301 so the GiST index on `footprint` is used."""
    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(422, "min_lon/min_lat must be smaller than max_lon/max_lat")
    expr = "ST_Transform(ST_MakeEnvelope(%(x0)s, %(y0)s, %(x1)s, %(y1)s, 4326), 3301)"
    return _spatial(expr, {"x0": min_lon, "y0": min_lat, "x1": max_lon, "y1": max_lat}, f, pg, geometry, match)


def _extract_polygon(body: dict) -> str:
    t = body.get("type")
    if t == "FeatureCollection" and body.get("features"):
        body = body["features"][0]; t = body.get("type")
    if t == "Feature":
        body = body.get("geometry") or {}; t = body.get("type")
    if t not in ("Polygon", "MultiPolygon") or "coordinates" not in body:
        raise HTTPException(422, "Body must be a GeoJSON Polygon/MultiPolygon (or a Feature containing one), lon/lat.")
    return json.dumps({"type": t, "coordinates": body["coordinates"]})


@router.post("/buildings/within", response_model=FeatureCollection, summary="Buildings inside a GeoJSON polygon")
def within_polygon(
    body: dict = Body(..., examples=[POLY_BODY_EXAMPLE]),
    geometry: Geometry = Query("footprint"),
    match: Match = Query("intersects"),
    f: Filters = Depends(filters), pg: Page = Depends(page),
):
    gj = _extract_polygon(body)
    expr = "ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%(gj)s), 4326), 3301)"
    try:
        ok = db.fetch_one(f"SELECT ST_IsValid({expr}) AS ok", {"gj": gj})["ok"]
    except Exception:
        raise HTTPException(422, "Could not parse the polygon.")
    if not ok:
        raise HTTPException(422, "Polygon is not valid (self-intersection or unclosed ring).")
    return _spatial(expr, {"gj": gj}, f, pg, geometry, match)


@router.get("/buildings/near", response_model=FeatureCollection, summary="Buildings near a point, nearest first")
def near(
    lon: float = Query(..., ge=-180, le=180, examples=[24.7536]),
    lat: float = Query(..., ge=-90, le=90, examples=[59.437]),
    radius_m: float = Query(300, gt=0, le=settings.max_radius_m, description="Metres (EPSG:3301 is metric)."),
    geometry: Geometry = Query("footprint"),
    f: Filters = Depends(filters), pg: Page = Depends(page),
):
    """`ST_DWithin` prunes with the GiST index, `<->` orders by distance. `distance_m` is centroid distance."""
    where, fp = _where(f, ["ST_DWithin(v.centroid, p.g, %(radius)s)"])
    params = {"lon": lon, "lat": lat, "radius": radius_m, "limit": pg.limit, "offset": pg.offset, **fp}
    base = ("FROM v_building_summary v, "
            "(SELECT ST_Transform(ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326), 3301) AS g) p" + where)
    total = db.fetch_one(f"SELECT count(*) AS n {base}", params)["n"]
    rows = db.fetch_all(
        f"SELECT {SUMMARY_COLS}, ST_Distance(v.centroid, p.g)::float8 AS distance_m, "
        f"{GEOM_SQL[geometry]} AS geom {base} "
        f"ORDER BY v.centroid <-> p.g, v.building_id LIMIT %(limit)s OFFSET %(offset)s", params)
    return _collection(rows, total, pg)


@router.get("/buildings", response_model=BuildingPage, summary="Search and filter buildings")
def list_buildings(
    sort_by: SortBy = Query("building_id"),
    sort_dir: Literal["asc", "desc"] = Query("asc"),
    f: Filters = Depends(filters), pg: Page = Depends(page),
):
    """Filter by action, confidence range, status (including failed), solar reliability and coverage class."""
    where, params = _where(f)
    params |= {"limit": pg.limit, "offset": pg.offset}
    col = SORT_COLUMNS[sort_by]
    direction = "ASC" if sort_dir == "asc" else "DESC"
    total = db.fetch_one(f"SELECT count(*) AS n FROM v_building_summary v{where}", params)["n"]
    rows = db.fetch_all(
        f"SELECT {SUMMARY_COLS} FROM v_building_summary v{where} "
        f"ORDER BY {col} {direction} NULLS LAST, v.building_id LIMIT %(limit)s OFFSET %(offset)s", params)
    return {"total": total, "limit": pg.limit, "offset": pg.offset, "items": rows}


def _get_summary(building_id: str) -> dict:
    row = db.fetch_one(f"SELECT {SUMMARY_COLS} FROM v_building_summary v WHERE v.building_id = %(id)s",
                       {"id": building_id})
    if not row:
        raise HTTPException(404, f"Building {building_id!r} not found")
    return row


@router.get("/buildings/{building_id}", response_model=BuildingDetail, summary="Building detail")
def building_detail(building_id: str):
    """Summary, full uncertainty record and footprint. Ground-truth scores are never returned."""
    s = _get_summary(building_id)
    unc = db.fetch_one("SELECT * FROM uncertainty WHERE recon_id = %(r)s", {"r": s["recon_id"]})
    if unc:
        unc.pop("recon_id", None)
    geom = db.fetch_one("SELECT ST_AsGeoJSON(ST_Transform(footprint, 4326), 6) AS g FROM buildings WHERE building_id = %(id)s",
                        {"id": building_id})["g"]
    n = db.fetch_one("SELECT count(*) AS n FROM roof_planes WHERE building_id = %(id)s", {"id": building_id})["n"]
    base = f"/buildings/{building_id}"
    return {"building": s, "uncertainty": unc, "footprint": json.loads(geom), "n_planes": n,
            "links": {"planes": f"{base}/planes", "model": f"{base}/model"}}


@router.get("/buildings/{building_id}/planes", response_model=list[Plane], summary="Roof planes of a building")
def building_planes(building_id: str):
    _get_summary(building_id)
    return db.fetch_all(
        """SELECT plane_id, tilt_deg, azimuth_deg, area_m2, n_points, rms_m,
                  ST_X(ST_Transform(centroid, 4326)) AS lon, ST_Y(ST_Transform(centroid, 4326)) AS lat,
                  mean_z, is_flat, viable, panel_tilt_deg, panel_azimuth_deg, usable_area_m2,
                  irradiation_kwh_m2, annual_kwh, annual_kwh_unshaded, shading_loss_frac,
                  horizon_max_deg, sky_view_factor
           FROM roof_planes WHERE building_id = %(id)s
           ORDER BY plane_id""", {"id": building_id})


MEDIA = {".glb": "model/gltf-binary", ".gltf": "model/gltf+json", ".obj": "text/plain", ".ply": "application/octet-stream"}


@router.get("/buildings/{building_id}/model", summary="Download the 3D model (GLB/OBJ) if one exists")
def building_model(building_id: str):
    row = db.fetch_one("""SELECT r.model_path FROM reconstructions r
                          WHERE r.building_id = %(id)s ORDER BY r.version DESC LIMIT 1""", {"id": building_id})
    if row is None:
        raise HTTPException(404, f"Building {building_id!r} not found")
    root = Path(settings.model_dir).resolve()
    if row["model_path"]:
        path = (root / row["model_path"]).resolve()
        if root not in path.parents or not path.is_file():
            log.warning("model file missing or outside MODEL_DIR: %s", row["model_path"])
            raise HTTPException(404, "Model file is not available on this server.")
    else:
        # Phase 8 export fallback: use the validated building-ID GLB collection.
        manifest_path = root / "glb_manifest.json"
        glb_path = root / "glb" / f"{building_id}.glb"
        if not manifest_path.is_file() or not glb_path.is_file():
            raise HTTPException(404, "No 3D model is available for this building.")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            registered = any(str(item.get("building_id")) == building_id
                             and item.get("glb_filename") == glb_path.name
                             for item in manifest.get("buildings", []))
        except (OSError, json.JSONDecodeError):
            registered = False
        if not registered:
            raise HTTPException(404, "No registered GLB is available for this building.")
        path = glb_path.resolve()
        if root not in path.parents:
            raise HTTPException(404, "Model file is not available on this server.")
    return FileResponse(path, media_type=MEDIA.get(path.suffix.lower(), "application/octet-stream"),
                        filename=path.name)
