from typing import Literal

from fastapi import APIRouter, Depends, Query

from .. import db
from ..filters import SUMMARY_COLS, Filters, Page, filters, page, where_sql
from ..schemas import RoofRanking

router = APIRouter(prefix="/rankings", tags=["rankings"])

METRICS = {"annual_kwh": "v.annual_kwh", "kwh_per_m2_roof": "v.kwh_per_m2_roof",
           "usable_roof_area_m2": "v.usable_roof_area_m2"}
Metric = Literal["annual_kwh", "kwh_per_m2_roof", "usable_roof_area_m2"]


@router.get("/roofs", response_model=RoofRanking, summary="Rank roofs by solar yield, kWh per m2 or usable area")
def rank_roofs(
    metric: Metric = Query("annual_kwh"),
    include_unreliable: bool = Query(
        False, description="Default ranks only `solar_reliability = ok` roofs. Set true to include every tier."),
    f: Filters = Depends(filters), pg: Page = Depends(page),
):
    """Every row carries `solar_reliability`, `action` and `p_bad`, so estimates are never shown as verified."""
    if not include_unreliable and not f.solar_reliability:
        f.solar_reliability = ["ok"]
    clauses, params = where_sql(f)
    clauses.append(f"{METRICS[metric]} IS NOT NULL")
    where = " WHERE " + " AND ".join(clauses)
    params |= {"limit": pg.limit, "offset": pg.offset}
    total = db.fetch_one(f"SELECT count(*) AS n FROM v_building_summary v{where}", params)["n"]
    rows = db.fetch_all(
        f"SELECT {SUMMARY_COLS}, {METRICS[metric]}::float8 AS metric_value FROM v_building_summary v{where} "
        f"ORDER BY {METRICS[metric]} DESC, v.building_id LIMIT %(limit)s OFFSET %(offset)s", params)
    for i, r in enumerate(rows):
        r["rank"] = pg.offset + i + 1
        r["metric"] = metric
    return {"metric": metric, "reliability_filter": f.solar_reliability,
            "total": total, "limit": pg.limit, "offset": pg.offset, "items": rows}
