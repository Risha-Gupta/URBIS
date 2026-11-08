from fastapi import APIRouter, HTTPException

from .. import db

router = APIRouter(tags=["meta"])


@router.get("/health", summary="Liveness")
def health():
    return {"status": "ok"}


@router.get("/ready", summary="Readiness: database reachable and seeded")
def ready():
    try:
        r = db.fetch_one("SELECT (SELECT count(*) FROM buildings) AS buildings, "
                         "(SELECT count(*) FROM roof_planes) AS roof_planes")
    except Exception:
        raise HTTPException(503, "database unavailable")
    if not r["buildings"]:
        raise HTTPException(503, "database is empty - run the ETL loader")
    return {"status": "ready", **r}
