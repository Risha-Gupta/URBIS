import logging
import time
from contextlib import asynccontextmanager


import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


from . import db
from .config import settings
from .routers import buildings, health, rankings, stats
from .jobs import jobs_router
from .jobs.db import SessionLocal
from .jobs.models import Job, JobEvent, ACTIVE


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("urbis")


DESCRIPTION = """
Searchable building database for **URBIS** (Tallinn, Building3D).


* Spatial data is stored in EPSG:3301 and served as WGS84 (EPSG:4326) GeoJSON.
* Map endpoints return GeoJSON FeatureCollections; `limit` is capped at 1000.
* Decisions use the current policy `phase6_rebased`; the old `phase4_old` rows are kept but never current.
* Ground-truth evaluation scores are never returned per building.
* Reconstruction jobs (`/jobs`) run in the background, stream progress over SSE, and keep every attempt as a result version.
"""


def recover_interrupted_jobs() -> int:
    """Mark jobs left in a running stage by a server stop as failed, so they can be retried."""
    count = 0
    with SessionLocal() as s:
        for j in s.query(Job).filter(Job.status.in_(ACTIVE)).all():
            msg = "server restarted during run"
            if j.versions:
                v = j.versions[-1]
                v.status, v.error = "failed", msg
                version_no = v.version_no
            else:
                version_no = None
            j.status = "failed"
            s.add(JobEvent(job_id=j.id, version_no=version_no, status="failed",
                           progress=j.progress, message=msg))
            count += 1
        s.commit()
    return count


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.open_pool()
    try:
        n = recover_interrupted_jobs()
        if n:
            log.warning("marked %d interrupted job(s) as failed", n)
    except Exception:
        log.exception("job recovery skipped")
    yield
    db.close_pool()


app = FastAPI(title="URBIS Geospatial Backend", version="1.0.0", description=DESCRIPTION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                   allow_methods=["GET", "POST"], allow_headers=["*"])


@app.middleware("http")
async def timing(request: Request, call_next):
    t = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time-ms"] = f"{(time.perf_counter() - t) * 1000:.1f}"
    return response


@app.exception_handler(psycopg.errors.QueryCanceled)
async def timeout_handler(request: Request, exc: Exception):
    return JSONResponse({"detail": "Query took too long; narrow the filters or area."}, status_code=503)


@app.exception_handler(psycopg.Error)
async def db_error_handler(request: Request, exc: Exception):
    log.exception("database error on %s", request.url.path)
    return JSONResponse({"detail": "Internal database error"}, status_code=500)


for r in (health.router, buildings.router, rankings.router, stats.router, jobs_router):
    app.include_router(r)