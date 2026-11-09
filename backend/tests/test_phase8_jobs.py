import os, json, time
os.environ.update(DATABASE_URL="sqlite:///./test_jobs.db", STEP_DELAY="0", RESULTS_DIR="data/test_results")
import numpy as np, pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.jobs import jobs_router
from app.jobs.db import Base, engine

app = FastAPI(); app.include_router(jobs_router)

@pytest.fixture(autouse=True)
def fresh():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine); yield

@pytest.fixture
def client(): return TestClient(app)

def sample(tmp_path, n=500, name="s.npy", bad=False):
    p = tmp_path / name
    a = np.random.rand(n, 3) * 50
    if bad: a[0, 0] = np.nan
    np.save(p, a); return p

def submit(client, p):
    return client.post("/jobs", files={"file": (p.name, open(p, "rb"))})

def wait(client, jid, timeout=10):
    t = time.time()
    while time.time() - t < timeout:
        j = client.get(f"/jobs/{jid}").json()
        if j["status"] in ("completed", "failed"): return j
        time.sleep(0.1)
    raise AssertionError("timeout")

def test_submit_returns_id_and_completes(client, tmp_path):
    r = submit(client, sample(tmp_path)); assert r.status_code == 202
    j = wait(client, r.json()["job_id"])
    assert j["status"] == "completed" and j["progress"] == 100 and len(j["versions"]) == 1
    assert j["versions"][0]["status"] == "succeeded" and j["versions"][0]["mesh_path"]

def test_invalid_inputs_rejected(client, tmp_path):
    assert submit(client, sample(tmp_path, n=10)).status_code == 422
    assert submit(client, sample(tmp_path, bad=True, name="b.npy")).status_code == 422
    bad = tmp_path / "x.pdf"; bad.write_bytes(b"x")
    assert submit(client, bad).status_code == 415

def test_sse_stage_order(client, tmp_path):
    jid = submit(client, sample(tmp_path)).json()["job_id"]
    wait(client, jid)
    body = client.get(f"/jobs/{jid}/events").text
    st = [json.loads(l[6:])["status"] for l in body.splitlines() if l.startswith("data: ")]
    assert st == ["queued", "preprocessing", "corner_detection", "edge_prediction",
                  "mesh_generation", "uncertainty_analysis", "correction", "completed"]

def test_failure_then_retry_creates_new_version(client, tmp_path):
    jid = submit(client, sample(tmp_path)).json()["job_id"]
    wait(client, jid)
    client.post(f"/jobs/{jid}/retry", json={"fail_at": "edge_prediction"}); j = wait(client, jid)
    assert j["status"] == "failed" and j["versions"][1]["status"] == "failed"
    assert "edge_prediction" in j["versions"][1]["error"] and j["versions"][1]["stage_reached"] == "edge_prediction"
    assert client.post(f"/jobs/{jid}/approve", json={}).status_code == 409
    client.post(f"/jobs/{jid}/retry", json={}); j = wait(client, jid)
    assert j["status"] == "completed" and [v["version_no"] for v in j["versions"]] == [1, 2, 3]
    assert j["versions"][2]["params"]["seed"] == j["versions"][1]["params"]["seed"] + 1
    assert j["versions"][0]["status"] == "succeeded"   # old attempt untouched

def test_retry_blocked_while_active(client, tmp_path):
    from app.jobs.db import SessionLocal
    from app.jobs.models import Job
    jid = submit(client, sample(tmp_path)).json()["job_id"]; wait(client, jid)
    with SessionLocal() as db: j = db.get(Job, jid); j.status = "mesh_generation"; db.commit()
    assert client.post(f"/jobs/{jid}/retry", json={}).status_code == 409

def test_comments_and_decisions(client, tmp_path):
    jid = submit(client, sample(tmp_path)).json()["job_id"]; wait(client, jid)
    assert client.post(f"/jobs/{jid}/comments", json={"author": "a", "body": "roof edge off"}).status_code == 201
    assert client.post(f"/jobs/{jid}/comments", json={"author": "a", "body": ""}).status_code == 422
    r = client.post(f"/jobs/{jid}/reject", json={"reviewer": "a", "note": "bad"}); assert r.json()["review_status"] == "rejected"
    client.post(f"/jobs/{jid}/retry", json={}); wait(client, jid)
    r = client.post(f"/jobs/{jid}/approve", json={"version_no": 2}).json()
    assert r["review_status"] == "approved" and r["final_version_id"] == r["versions"][1]["id"]
    assert client.post(f"/jobs/{jid}/retry", json={}).status_code == 409
    j = client.get(f"/jobs/{jid}").json(); assert len(j["comments"]) >= 2

def test_unknown_job_404(client):
    assert client.get("/jobs/nope").status_code == 404
    assert client.get("/jobs/nope/events").status_code == 404