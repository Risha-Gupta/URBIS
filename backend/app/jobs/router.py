import asyncio, json, shutil
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import get_db, SessionLocal, Base, engine
from .models import Job, ModelResultVersion, JobEvent, Comment, ACTIVE
from .pipeline import load_points, StageError, DEFAULT_PARAMS
from .runner import create_version, run_version

Base.metadata.create_all(engine)
router = APIRouter(prefix="/jobs", tags=["jobs"])
UPLOADS = Path("data/uploads"); UPLOADS.mkdir(parents=True, exist_ok=True)
TERMINAL = {"completed", "failed"}

class RetryIn(BaseModel):
    score_thr: float = Field(0.5, ge=0, le=1)
    passes: int = Field(16, ge=1, le=64)
    seed: int | None = None
    fail_at: str | None = None

class DecisionIn(BaseModel):
    version_no: int | None = None
    reviewer: str = "reviewer"
    note: str = ""

class CommentIn(BaseModel):
    version_no: int | None = None
    author: str = Field(min_length=1, max_length=64)
    body: str = Field(min_length=1, max_length=2000)

def get_job(db, job_id) -> Job:
    job = db.get(Job, job_id)
    if not job: raise HTTPException(404, "job not found")
    return job

def get_ver(job, version_no=None) -> ModelResultVersion:
    if not job.versions: raise HTTPException(409, "no versions")
    if version_no is None: return job.versions[-1]
    v = next((x for x in job.versions if x.version_no == version_no), None)
    if not v: raise HTTPException(404, "version not found")
    return v

def ver_out(v):
    return {c.name: getattr(v, c.name) for c in v.__table__.columns}

def job_out(j):
    return {"job_id": j.id, "building_id": j.building_id, "status": j.status, "progress": j.progress,
            "review_status": j.review_status, "final_version_id": j.final_version_id,
            "versions": [ver_out(v) for v in j.versions]}

@router.post("", status_code=202)
async def submit(bg: BackgroundTasks, file: UploadFile = File(...), building_id: str | None = Form(None),
                 db: Session = Depends(get_db)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".npy", ".xyz", ".txt"}: raise HTTPException(415, "use .npy, .xyz or .txt")
    job = Job(building_id=building_id, input_path="")
    dest = UPLOADS / f"{job.id}{ext}"
    with open(dest, "wb") as f: shutil.copyfileobj(file.file, f)
    try: load_points(str(dest))
    except Exception as e:
        dest.unlink(missing_ok=True); raise HTTPException(422, f"invalid LiDAR sample: {e}")
    job.input_path = str(dest); db.add(job); db.commit()
    ver = create_version(db, job, {})
    db.add(JobEvent(job_id=job.id, version_no=1, status="queued", progress=0, message="accepted")); db.commit()
    bg.add_task(run_version, job.id, ver.id)
    return {"job_id": job.id, "status": "queued", "events_url": f"/jobs/{job.id}/events"}

@router.get("")
def list_jobs(status: str | None = None, db: Session = Depends(get_db)):
    q = select(Job).order_by(Job.created_at.desc()).limit(200)
    if status: q = q.where(Job.status == status)
    return [job_out(j) for j in db.scalars(q)]

@router.get("/{job_id}")
def get_one(job_id: str, db: Session = Depends(get_db)):
    j = get_job(db, job_id)
    out = job_out(j)
    out["comments"] = [{"version_id": c.version_id, "author": c.author, "body": c.body,
                        "created_at": c.created_at} for c in db.scalars(select(Comment).where(Comment.job_id == job_id))]
    return out

@router.get("/{job_id}/versions")
def versions(job_id: str, db: Session = Depends(get_db)):
    return [ver_out(v) for v in get_job(db, job_id).versions]

@router.post("/{job_id}/retry", status_code=202)
def retry(job_id: str, body: RetryIn, bg: BackgroundTasks, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if job.status in ACTIVE: raise HTTPException(409, f"job is {job.status}; wait for it to finish")
    if job.review_status == "approved": raise HTTPException(409, "job already approved")
    params = body.model_dump(); last = job.versions[-1]
    params["seed"] = body.seed if body.seed is not None else (last.params.get("seed", 0) + 1)
    ver = create_version(db, job, params)
    job.status, job.progress, job.review_status = "queued", 0, "none"
    db.add(JobEvent(job_id=job.id, version_no=ver.version_no, status="queued", progress=0,
                    message=f"retry -> v{ver.version_no}")); db.commit()
    bg.add_task(run_version, job.id, ver.id)
    return {"job_id": job.id, "version_no": ver.version_no, "status": "queued"}

def decide(job_id, body, db, decision):
    job = get_job(db, job_id)
    if job.status != "completed": raise HTTPException(409, "only completed jobs can be reviewed")
    ver = get_ver(job, body.version_no)
    if ver.status != "succeeded": raise HTTPException(409, "version did not succeed")
    if job.review_status in {"approved", "rejected"} and job.final_version_id == ver.id:
        raise HTTPException(409, f"already {job.review_status}")
    ver.decision = decision; job.review_status = decision; job.final_version_id = ver.id
    if body.note: db.add(Comment(job_id=job.id, version_id=ver.id, author=body.reviewer, body=f"[{decision}] {body.note}"))
    db.commit()
    return job_out(job)

@router.post("/{job_id}/approve")
def approve(job_id: str, body: DecisionIn, db: Session = Depends(get_db)): return decide(job_id, body, db, "approved")

@router.post("/{job_id}/reject")
def reject(job_id: str, body: DecisionIn, db: Session = Depends(get_db)): return decide(job_id, body, db, "rejected")

@router.post("/{job_id}/comments", status_code=201)
def comment(job_id: str, body: CommentIn, db: Session = Depends(get_db)):
    job = get_job(db, job_id); ver = get_ver(job, body.version_no)
    c = Comment(job_id=job_id, version_id=ver.id, author=body.author, body=body.body)
    db.add(c); db.commit()
    return {"id": c.id, "version_no": ver.version_no}

@router.get("/{job_id}/events")
async def events(job_id: str, request: Request):
    def fetch(after):
        with SessionLocal() as db:
            return [(e.id, e.version_no, e.status, e.progress, e.message) for e in
                    db.scalars(select(JobEvent).where(JobEvent.job_id == job_id, JobEvent.id > after).order_by(JobEvent.id))]
    with SessionLocal() as db:
        if not db.get(Job, job_id): raise HTTPException(404, "job not found")
    after = int(request.headers.get("last-event-id", 0) or 0)

    async def gen():
        nonlocal after
        idle = 0
        while True:
            if await request.is_disconnected(): return
            rows = await asyncio.to_thread(fetch, after)
            for id_, vn, st, pr, msg in rows:
                after = id_; idle = 0
                yield f"id: {id_}\nevent: progress\ndata: {json.dumps({'job_id': job_id, 'version_no': vn, 'status': st, 'progress': pr, 'message': msg})}\n\n"
                if st in TERMINAL: return
            idle += 1
            if idle % 20 == 0: yield ": keepalive\n\n"
            await asyncio.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@router.get("/{job_id}/versions/{version_no}/model")
def model(job_id: str, version_no: int, db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse
    v = get_ver(get_job(db, job_id), version_no)
    if not v.mesh_path or not Path(v.mesh_path).exists(): raise HTTPException(404, "no mesh for this version")
    return FileResponse(v.mesh_path, filename=f"{job_id}_v{version_no}.obj")