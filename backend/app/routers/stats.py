from typing import Literal

from fastapi import APIRouter, Query

from .. import db
from ..schemas import Summary

router = APIRouter(tags=["stats"])

CAVEATS = [
    "Counts and GWh use the current policy (phase6_rebased); the old phase4_old rows are kept but never current.",
    "Ground-truth 'bad' means min-F1 (1 m) <= 0.3265. It measures reconstruction quality, not solar error.",
    "Quote policy results from the held-out half (half=hold); the thresholds were fitted on the tuning half.",
    "Phase 6 found the rule policy costs more than accepting everything under the assumed costs (0.438 vs 0.360); "
    "it breaks even only if a missed bad building costs about 2.7x a review.",
    "Shading is a lower bound (no trees); snow losses are not modelled; footprints are LiDAR convex hulls.",
]


def _scope(half):
    return {"scope": half or "all", "half": half}


def _counts(sql: str, params: dict) -> dict:
    return {str(r["k"]): r["n"] for r in db.fetch_all(sql, params)}


@router.get("/stats/summary", response_model=Summary, summary="Counts by action, total GWh and yield at risk")
def summary(half: Literal["tune", "hold"] | None = Query(
        None, description="Restrict to one half. Use `hold` for any number you quote in a report.")):
    p = _scope(half)
    flt = "(%(half)s::text IS NULL OR v.half = %(half)s)"
    n = db.fetch_one(f"SELECT count(*) AS n FROM v_building_summary v WHERE {flt}", p)["n"]
    by = lambda col: _counts(f"SELECT COALESCE(v.{col}, 'none') AS k, count(*) AS n FROM v_building_summary v "
                             f"WHERE {flt} GROUP BY 1 ORDER BY 1", p)
    by_action = by("action")
    gwh = db.fetch_one(f"""SELECT COALESCE(sum(annual_kwh), 0)::float8 / 1e6 AS shaded,
                                  COALESCE(sum(annual_kwh_unshaded), 0)::float8 / 1e6 AS unshaded
                           FROM v_building_summary v WHERE {flt}""", p)
    gwh_action = {r["k"]: r["g"] for r in db.fetch_all(
        f"""SELECT COALESCE(action, 'none') AS k, COALESCE(sum(annual_kwh), 0)::float8 / 1e6 AS g
            FROM v_building_summary v WHERE {flt} GROUP BY 1 ORDER BY 1""", p)}
    pol = db.fetch_one("""SELECT policy_version, min(t_low) AS t_low, min(t_acc) AS t_acc, count(*) AS n
                          FROM decisions WHERE is_current GROUP BY policy_version LIMIT 1""") or {}
    risk = db.fetch_one(f"""
        SELECT count(*) AS n,
               avg(e.is_bad::float8) AS bad_share_of_buildings,
               sum(s.annual_kwh)::float8 / 1e6 AS total_gwh,
               COALESCE(sum(s.annual_kwh) FILTER (WHERE e.is_bad = 1), 0)::float8 / 1e6 AS gwh_bad,
               COALESCE(sum(s.annual_kwh) FILTER (WHERE e.is_bad = 1 AND v.action <> 'ESCALATE'), 0)::float8 / 1e6 AS gwh_acc_bad
        FROM evaluation e
        JOIN solar_buildings s USING (building_id)
        JOIN v_building_summary v USING (building_id)
        WHERE {flt.replace('v.half', 'e.half')}""", p)
    yar = None
    if risk and risk["n"] and risk["total_gwh"]:
        yar = {"basis": f"ground-truth min-F1 labels, scope={p['scope']}, aggregate only",
               "n_buildings": risk["n"], "total_gwh": risk["total_gwh"],
               "bad_share_of_buildings": risk["bad_share_of_buildings"],
               "gwh_in_bad_buildings": risk["gwh_bad"],
               "share_in_bad_accept_all": risk["gwh_bad"] / risk["total_gwh"],
               "gwh_in_accepted_bad_buildings": risk["gwh_acc_bad"],
               "share_in_accepted_bad_rule": risk["gwh_acc_bad"] / risk["total_gwh"]}
    return {"scope": p["scope"], "n_buildings": n, "by_action": by_action, "by_status": by("status"),
            "by_solar_reliability": by("solar_reliability"), "by_coverage_class": by("coverage_class"),
            "escalate_rate": (by_action.get("ESCALATE", 0) / n) if n else 0.0,
            "policy": {"policy_version": pol.get("policy_version"), "t_low": pol.get("t_low"),
                       "t_acc": pol.get("t_acc"), "label_threshold_min_f1": 0.3265},
            "total_gwh_shaded": gwh["shaded"], "total_gwh_unshaded": gwh["unshaded"],
            "gwh_by_action": gwh_action, "yield_at_risk": yar, "caveats": CAVEATS}


@router.get("/datasets", tags=["meta"], summary="Datasets in the database")
def datasets():
    return db.fetch_all("SELECT dataset_id, name, source, crs, notes FROM datasets ORDER BY dataset_id")


@router.get("/robustness/summary", tags=["meta"],
            summary="City3D (AHN3) out-of-distribution robustness check")
def robustness():
    rows = db.fetch_all("""
        SELECT COALESCE(subset, 'all') AS subset, count(*) AS n,
               avg(model_confidence)::float8 AS mean_confidence,
               avg((num_predicted_corners = 0)::int)::float8 AS zero_corner_share,
               avg((action = 'ESCALATE')::int)::float8 AS escalated_share,
               avg(min_f1_1m)::float8 AS mean_min_f1, avg(is_bad)::float8 AS bad_share
        FROM robustness_scores GROUP BY 1 ORDER BY 1""")
    return {"note": "Out-of-distribution robustness only, not accuracy: the reference is algorithm-generated "
                    "(~40 corners per building vs 14.4 in Tallinn) and the clouds are very sparse.",
            "subsets": rows}
