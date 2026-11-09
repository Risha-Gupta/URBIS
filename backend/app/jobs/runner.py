import time, traceback
from datetime import datetime, timezone
from .db import SessionLocal
from .models import Job, ModelResultVersion, JobEvent, STAGES, JobStatus
from .pipeline import StubPipeline, STEP_DELAY, StageError, DEFAULT_PARAMS

PIPELINE = StubPipeline()

def emit(db, job, ver, status, progress, msg=""):
    job.status, job.progress = status, progress
    db.add(JobEvent(job_id=job.id, version_no=ver.version_no, status=status, progress=progress, message=msg))
    db.commit()

def create_version(db, job, params):
    n = len(job.versions) + 1
    ver = ModelResultVersion(job_id=job.id, version_no=n, params={**DEFAULT_PARAMS, **params})
    db.add(ver); db.commit(); db.refresh(ver); db.refresh(job)
    return ver

def run_version(job_id: str, version_id: int):
    db = SessionLocal()
    try:
        job = db.get(Job, job_id); ver = db.get(ModelResultVersion, version_id)
        ctx = {"job_id": job_id, "input_path": job.input_path,
               "params": ver.params, "version_no": ver.version_no}
        n = len(STAGES)
        for i, stage in enumerate(STAGES):
            emit(db, job, ver, stage.value, int(100 * i / n), f"{stage.value} started")
            ver.stage_reached = stage.value; db.commit()
            time.sleep(STEP_DELAY)
            if ver.params.get("fail_at") == stage.value:
                raise StageError(f"injected failure at {stage.value}")
            getattr(PIPELINE, stage.value)(ctx)
        ver.status, ver.confidence, ver.action = "succeeded", ctx["confidence"], ctx["action"]
        ver.mesh_path, ver.n_corners, ver.n_edges = ctx["mesh_path"], len(ctx["corners"]), len(ctx["edges"])
        ver.finished_at = datetime.now(timezone.utc)
        job.review_status = "pending" if ver.action != "ACCEPT" else "none"
        db.commit()
        emit(db, job, ver, "completed", 100, f"action={ver.action} confidence={ver.confidence}")
    except Exception as e:
        db.rollback()
        job = db.get(Job, job_id); ver = db.get(ModelResultVersion, version_id)
        ver.status, ver.error = "failed", f"{type(e).__name__}: {e}"
        ver.finished_at = datetime.now(timezone.utc); db.commit()
        emit(db, job, ver, "failed", job.progress, ver.error)
        if not isinstance(e, StageError): traceback.print_exc()
    finally:
        db.close()