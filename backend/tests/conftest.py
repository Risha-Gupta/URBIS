import os

import psycopg
import pytest
from fastapi.testclient import TestClient

DSN = os.environ.get("DATABASE_URL", "postgresql://urbis:urbis@localhost:5432/urbis")


def _db_ready() -> bool:
    try:
        with psycopg.connect(DSN, connect_timeout=3) as c:
            return c.execute("SELECT count(*) FROM buildings").fetchone()[0] > 0
    except Exception:
        return False


needs_db = pytest.mark.skipif(not _db_ready(), reason="seeded PostGIS database not reachable (set DATABASE_URL)")


@pytest.fixture(scope="session")
def client():
    os.environ["DATABASE_URL"] = DSN
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def sql():
    with psycopg.connect(DSN) as conn:
        yield lambda q, p=None: conn.execute(q, p or {}).fetchall()
