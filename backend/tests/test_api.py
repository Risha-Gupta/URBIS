"""Acceptance checks against a seeded database (docker compose up db + etl)."""
import pytest

from .conftest import needs_db

pytestmark = needs_db

BOX = dict(min_lon=24.74, min_lat=59.43, max_lon=24.77, max_lat=59.445)
BOX_SQL = "ST_Transform(ST_MakeEnvelope(24.74, 59.43, 24.77, 59.445, 4326), 3301)"


def test_row_counts(client, sql):
    assert sql("SELECT count(*) FROM buildings")[0][0] == 3207
    assert sql("SELECT count(*) FROM roof_planes")[0][0] == 9116
    r = client.get("/ready").json()
    assert (r["buildings"], r["roof_planes"]) == (3207, 9116)


def test_near_matches_manual_distance_order(client, sql):
    lon, lat, rad = 24.7536, 59.437, 400
    r = client.get("/buildings/near", params=dict(lon=lon, lat=lat, radius_m=rad, limit=50)).json()
    got = [f["id"] for f in r["features"]]
    dists = [f["properties"]["distance_m"] for f in r["features"]]
    assert dists == sorted(dists) and len(got) > 0
    want = [x[0] for x in sql("""
        WITH p AS (SELECT ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 3301) AS g)
        SELECT b.building_id FROM buildings b, p WHERE ST_Distance(b.centroid, p.g) <= %s
        ORDER BY ST_Distance(b.centroid, p.g), b.building_id LIMIT 50""", (lon, lat, rad))]
    assert got == want


def test_within_count_matches_direct_sql(client, sql):
    r = client.get("/buildings/within", params=BOX).json()
    want = sql(f"SELECT count(*) FROM buildings WHERE ST_Intersects(footprint, {BOX_SQL})")[0][0]
    assert r["numberMatched"] == want and want > 0


def test_polygon_post_matches_bbox_get(client):
    poly = {"type": "Polygon", "coordinates": [[[24.74, 59.43], [24.77, 59.43], [24.77, 59.445],
                                                 [24.74, 59.445], [24.74, 59.43]]]}
    a = client.post("/buildings/within", json=poly).json()["numberMatched"]
    b = client.get("/buildings/within", params=BOX).json()["numberMatched"]
    assert a == b


def test_invalid_polygon_rejected(client):
    bowtie = {"type": "Polygon", "coordinates": [[[24.7, 59.4], [24.8, 59.5], [24.8, 59.4], [24.7, 59.5], [24.7, 59.4]]]}
    assert client.post("/buildings/within", json=bowtie).status_code == 422


def test_pagination_cap_and_total(client):
    r = client.get("/buildings", params={"limit": 1000}).json()
    assert r["total"] == 3207 and len(r["items"]) == 1000
    assert len(client.get("/buildings", params={"limit": 1000, "offset": 3000}).json()["items"]) == 207


def test_escalate_share_of_heldout_matches_phase6(client):
    s = client.get("/stats/summary", params={"half": "hold"}).json()
    assert s["n_buildings"] == 1604
    assert round(100 * s["escalate_rate"], 1) == 29.5
    assert s["policy"]["policy_version"] == "phase6_rebased"
    assert abs(s["policy"]["t_low"] - 0.7165) < 1e-3 and abs(s["policy"]["t_acc"] - 0.7393) < 1e-3
    r = s["yield_at_risk"]
    assert r and 0 < r["share_in_accepted_bad_rule"] < r["share_in_bad_accept_all"] < 1


def test_total_gwh(client):
    s = client.get("/stats/summary").json()
    assert s["n_buildings"] == 3207 and s["total_gwh_shaded"] == pytest.approx(42.6, abs=0.1)


def test_failed_filter(client):
    r = client.get("/buildings", params={"status": "failed"}).json()
    assert r["total"] == 13
    assert {i["status"] for i in r["items"]} == {"failed_zero_corners", "failed_no_roof_planes"}
    assert client.get("/buildings", params={"status": "failed_zero_corners"}).json()["total"] == 7


def test_action_and_confidence_filters(client, sql):
    r = client.get("/buildings", params={"action": "ESCALATE", "max_confidence": 0.7, "limit": 1000}).json()
    want = sql("""SELECT count(*) FROM v_building_summary WHERE action='ESCALATE' AND model_confidence <= 0.7""")[0][0]
    assert r["total"] == want
    assert all(i["model_confidence"] <= 0.7 for i in r["items"])


def test_ranking_defaults_to_ok_only_and_shows_reliability(client):
    r = client.get("/rankings/roofs", params={"limit": 20}).json()
    assert r["items"][0]["rank"] == 1
    assert all(i["solar_reliability"] == "ok" for i in r["items"])
    vals = [i["metric_value"] for i in r["items"]]
    assert vals == sorted(vals, reverse=True)
    allr = client.get("/rankings/roofs", params={"include_unreliable": True, "limit": 1}).json()
    assert allr["total"] > r["total"]


def test_detail_planes_and_no_ground_truth_leak(client):
    bid = client.get("/buildings", params={"limit": 1}).json()["items"][0]["building_id"]
    d = client.get(f"/buildings/{bid}").json()
    flat = str(d)
    assert "min_f1" not in flat and "is_bad" not in flat
    planes = client.get(f"/buildings/{bid}/planes").json()
    assert len(planes) == d["n_planes"]
    assert client.get("/buildings/does-not-exist").status_code == 404


def test_model_404_when_not_generated(client):
    bid = client.get("/buildings", params={"limit": 1}).json()["items"][0]["building_id"]
    assert client.get(f"/buildings/{bid}/model").status_code == 404


def test_robustness_summary(client):
    r = client.get("/robustness/summary").json()
    assert sum(s["n"] for s in r["subsets"]) == 1000


def test_gist_index_used_for_spatial_queries(sql):
    import psycopg
    from .conftest import DSN
    with psycopg.connect(DSN) as conn:
        conn.execute("SET LOCAL enable_seqscan = off")  # 3k rows: planner may legitimately seq-scan
        plan = "\n".join(r[0] for r in conn.execute(
            f"EXPLAIN SELECT building_id FROM buildings WHERE ST_Intersects(footprint, {BOX_SQL})").fetchall())
    assert "buildings_footprint_gix" in plan, plan
