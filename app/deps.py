"""FastAPI dependencies — DB session, auth, etc."""

import hashlib
import logging
from typing import Generator

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import SessionLocal

logger = logging.getLogger(__name__)


# ============================================================
# DATABASE SESSION
# ============================================================

def get_db() -> Generator[Session, None, None]:
    """Yields a SQLAlchemy session and closes it after use.

    Usage in endpoints::

        @app.get("/things")
        def list_things(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================
# ADVISORY LOCK HELPERS
# ============================================================

def _advisory_lock_key(job_id: str) -> int:
    """Deterministic 64-bit signed integer from *job_id*.

    Used with ``pg_advisory_lock(bigint)`` / ``pg_try_advisory_lock(bigint)``.
    """
    digest = hashlib.sha256(job_id.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, byteorder="big", signed=True)


def acquire_job_lock(db: Session, job_id: str) -> bool:
    """Try to acquire a session-level advisory lock for *job_id*.

    Returns ``True`` if the lock was acquired, ``False`` if another
    session already holds it.  The lock is released when the session
    closes or ``release_job_lock()`` is called explicitly.

    For SQLite (testing), always returns True (no-op).
    """
    from sqlalchemy import text

    lock_key = _advisory_lock_key(job_id)

    # SQLite doesn't support pg_advisory_lock — skip gracefully
    if "sqlite" in str(db.get_bind().url):
        logger.info(
            "Advisory lock (SQLite skip) job=%s key=%s",
            job_id,
            lock_key,
        )
        return True

    result = db.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": lock_key},
    ).scalar()
    logger.info(
        "Advisory lock job=%s key=%s acquired=%s",
        job_id,
        lock_key,
        result,
    )
    return bool(result)


def release_job_lock(db: Session, job_id: str) -> None:
    """Release the session-level advisory lock for *job_id*."""
    from sqlalchemy import text

    lock_key = _advisory_lock_key(job_id)

    if "sqlite" in str(db.get_bind().url):
        logger.info("Advisory unlock (SQLite skip) job=%s key=%s", job_id, lock_key)
        return

    db.execute(
        text("SELECT pg_advisory_unlock(:key)"),
        {"key": lock_key},
    )
    logger.info("Advisory unlock job=%s key=%s", job_id, lock_key)


# ============================================================
# AUTH STUB  (replace with real Cognito / JWT validation)
# ============================================================

def get_current_user() -> dict:
    """Placeholder auth dependency.

    In production, decode the JWT from the Authorization header and
    return the user claims dict (with at least ``sub``).
    """
    return {"sub": "REEMPLAZAR_USER"}
