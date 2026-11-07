import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.environ.get("DATABASE_URL", "postgresql://urbis:urbis@localhost:5432/urbis")
    model_dir: str = os.environ.get("MODEL_DIR", "/models")
    cors_origins: tuple = tuple(
        o.strip() for o in os.environ.get(
            "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",") if o.strip())
    pool_min: int = int(os.environ.get("POOL_MIN", "1"))
    pool_max: int = int(os.environ.get("POOL_MAX", "8"))
    statement_timeout_ms: int = int(os.environ.get("STATEMENT_TIMEOUT_MS", "15000"))
    max_limit: int = 1000
    max_radius_m: float = 5000.0


settings = Settings()
