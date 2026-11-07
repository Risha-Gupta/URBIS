"""Shared query filters and SQL building. Every value is passed as a bound parameter;
the only text interpolated into SQL comes from the whitelists below."""
from dataclasses import dataclass
from typing import Literal

from fastapi import Query

from .config import settings

Action = Literal["ACCEPT", "ACCEPT_FLAG", "ESCALATE"]
Status = Literal["completed", "failed", "failed_zero_corners", "failed_no_roof_planes"]
Reliability = Literal["ok", "estimate_flagged", "estimate_escalated",
                      "area_outlier", "low_plane_coverage", "no_roof_planes"]
Coverage = Literal["dense", "sparse"]
Half = Literal["tune", "hold"]

SORT_COLUMNS = {
    "building_id": "v.building_id",
    "model_confidence": "v.model_confidence",
    "annual_kwh": "v.annual_kwh",
    "kwh_per_m2_roof": "v.kwh_per_m2_roof",
    "usable_roof_area_m2": "v.usable_roof_area_m2",
    "p_bad": "v.p_bad",
    "review_rank": "v.review_rank",
}
SortBy = Literal["building_id", "model_confidence", "annual_kwh", "kwh_per_m2_roof",
                 "usable_roof_area_m2", "p_bad", "review_rank"]

SUMMARY_COLS = """
    v.building_id, v.dataset_id, v.half, v.coverage_class, v.num_points,
    v.footprint_area_m2, v.footprint_source,
    ST_X(v.centroid_wgs84) AS lon, ST_Y(v.centroid_wgs84) AS lat,
    v.recon_id, v.version, v.status, v.n_pred_corners, v.n_pred_edges,
    (v.model_path IS NOT NULL) AS has_model, v.created_at,
    v.model_confidence, v.combined_confidence, v.confidence_class,
    v.action, v.decision_policy,
    v.total_roof_area_m2, v.usable_roof_area_m2, v.annual_kwh, v.annual_kwh_unshaded,
    v.shading_loss_frac, v.kwh_per_m2_roof, v.dominant_tilt_deg, v.dominant_azimuth_deg,
    v.solar_reliability, v.p_bad, v.review_rank, v.solar_review
"""


@dataclass
class Filters:
    action: list[str] | None = None
    status: list[str] | None = None
    min_confidence: float | None = None
    max_confidence: float | None = None
    solar_reliability: list[str] | None = None
    coverage_class: str | None = None
    half: str | None = None
    min_kwh: float | None = None
    review_only: bool | None = None
    dataset_id: str | None = None


def filters(
    action: list[Action] | None = Query(None, description="One or more triage actions."),
    status: list[Status] | None = Query(
        None, description="Reconstruction status. `failed` = zero corners OR no roof planes."),
    min_confidence: float | None = Query(None, ge=0, le=1, description="Phase 3 model_confidence, lower bound."),
    max_confidence: float | None = Query(None, ge=0, le=1, description="Phase 3 model_confidence, upper bound."),
    solar_reliability: list[Reliability] | None = Query(None),
    coverage_class: Coverage | None = Query(None),
    half: Half | None = Query(None, description="`hold` = held-out half (use for quoted results); `tune` = tuning half."),
    min_kwh: float | None = Query(None, ge=0, description="Minimum annual_kwh (shaded)."),
    review_only: bool | None = Query(None, description="Only buildings in the solar review queue."),
    dataset_id: str | None = Query(None),
) -> Filters:
    if min_confidence is not None and max_confidence is not None and min_confidence > max_confidence:
        from fastapi import HTTPException
        raise HTTPException(422, "min_confidence must be <= max_confidence")
    if status and "failed" in status:
        status = [s for s in status if s != "failed"] + ["failed_zero_corners", "failed_no_roof_planes"]
    return Filters(action, status, min_confidence, max_confidence, solar_reliability,
                   coverage_class, half, min_kwh, review_only, dataset_id)


@dataclass
class Page:
    limit: int
    offset: int


def page(limit: int = Query(100, ge=1, le=settings.max_limit, description="Max 1000."),
         offset: int = Query(0, ge=0)) -> Page:
    return Page(limit, offset)


def where_sql(f: Filters) -> tuple[list[str], dict]:
    c, p = [], {}
    if f.action:
        c.append("v.action = ANY(%(action)s)"); p["action"] = list(f.action)
    if f.status:
        c.append("v.status = ANY(%(status)s)"); p["status"] = list(f.status)
    if f.min_confidence is not None:
        c.append("v.model_confidence >= %(min_conf)s"); p["min_conf"] = f.min_confidence
    if f.max_confidence is not None:
        c.append("v.model_confidence <= %(max_conf)s"); p["max_conf"] = f.max_confidence
    if f.solar_reliability:
        c.append("v.solar_reliability = ANY(%(rel)s)"); p["rel"] = list(f.solar_reliability)
    if f.coverage_class:
        c.append("v.coverage_class = %(cov)s"); p["cov"] = f.coverage_class
    if f.half:
        c.append("v.half = %(half)s"); p["half"] = f.half
    if f.min_kwh is not None:
        c.append("v.annual_kwh >= %(min_kwh)s"); p["min_kwh"] = f.min_kwh
    if f.review_only:
        c.append("v.solar_review IS TRUE")
    if f.dataset_id:
        c.append("v.dataset_id = %(dataset_id)s"); p["dataset_id"] = f.dataset_id
    return c, p
