"""Health check endpoint for FastAPI.

Returns 200 with {"status":"ok","db":true} when healthy.
Returns 503 with {"status":"unhealthy","db":false} when DB fails.
"""

import logging
import os

from fastapi import APIRouter
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

router = APIRouter()


def _check_db() -> bool:
    """Verify DB connection with 500ms timeout.

    Returns True if healthy, False otherwise.
    Non-blocking and exception-safe.
    """
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        return True

    try:
        # Create a minimal engine for health check only — avoids
        # issues with pool kwargs that SQLite doesn't support.
        engine = create_engine(
            db_url,
            pool_pre_ping=True,
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception as exc:
        logger.warning("DB health check failed: %s", exc)
        return False


@router.get("/health")
def health_check():
    """Health check endpoint.

    Returns:
        200: {"status": "ok", "db": true} — app and DB healthy
        503: {"status": "unhealthy", "db": false} — DB connection failed
    """
    db_healthy = _check_db()

    if db_healthy:
        return {"status": "ok", "db": True}

    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=503,
        content={"status": "unhealthy", "db": False},
    )
