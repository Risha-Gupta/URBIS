"""Request validation runs before any database access, so these need no database."""
from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)  # no lifespan: pool is not opened


def test_limit_above_1000_rejected():
    assert c.get("/buildings", params={"limit": 1001}).status_code == 422


def test_bad_enum_rejected():
    assert c.get("/buildings", params={"action": "MAYBE"}).status_code == 422


def test_bbox_requires_all_corners():
    assert c.get("/buildings/within", params={"min_lon": 24.7}).status_code == 422


def test_bbox_min_greater_than_max_rejected():
    r = c.get("/buildings/within", params={"min_lon": 25, "min_lat": 59, "max_lon": 24, "max_lat": 60})
    assert r.status_code == 422


def test_radius_cap():
    assert c.get("/buildings/near", params={"lon": 24.7, "lat": 59.4, "radius_m": 99999}).status_code == 422


def test_polygon_body_must_be_polygon():
    r = c.post("/buildings/within", json={"type": "Point", "coordinates": [24.7, 59.4]})
    assert r.status_code == 422


def test_confidence_range_order():
    assert c.get("/buildings", params={"min_confidence": 0.9, "max_confidence": 0.1}).status_code == 422


def test_openapi_documents_all_endpoints():
    paths = c.get("/openapi.json").json()["paths"]
    for p in ["/buildings", "/buildings/within", "/buildings/near", "/buildings/{building_id}",
              "/buildings/{building_id}/planes", "/buildings/{building_id}/model",
              "/rankings/roofs", "/stats/summary", "/health", "/ready"]:
        assert p in paths, p
