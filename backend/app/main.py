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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("urbis")

DESCRIPTION = """
Searchable building database for **URBIS** (Tallinn, Building3D).

* Spatial data is stored in EPSG:3301 and served as WGS84 (EPSG:4326) GeoJSON.
* Map endpoints return GeoJSON FeatureCollections; `limit` is capped at 1000.
* Decisions use the current policy `phase6_rebased`; the old `phase4_old` rows are kept but never current.
* Ground-truth evaluation scores are never returned per building.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.open_pool()
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


for r in (health.router, buildings.router, rankings.router, stats.router):
    app.include_router(r)
