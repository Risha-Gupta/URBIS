import logging
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings

log = logging.getLogger("urbis.db")
_pool: ConnectionPool | None = None


def open_pool() -> None:
    global _pool
    _pool = ConnectionPool(
        settings.database_url,
        min_size=settings.pool_min,
        max_size=settings.pool_max,
        kwargs={"row_factory": dict_row,
                "options": f"-c statement_timeout={settings.statement_timeout_ms}"},
        open=False,
    )
    _pool.open(wait=True, timeout=30)
    log.info("database pool open")


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connection():
    if _pool is None:
        raise RuntimeError("database pool is not open")
    with _pool.connection() as conn:
        yield conn


def fetch_all(sql: str, params: dict | None = None) -> list[dict]:
    with connection() as conn:
        return conn.execute(sql, params or {}).fetchall()


def fetch_one(sql: str, params: dict | None = None) -> dict | None:
    with connection() as conn:
        return conn.execute(sql, params or {}).fetchone()
