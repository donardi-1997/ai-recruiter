"""PostgreSQL advisory locking used by ranking recalculation."""

import hashlib

from sqlalchemy import text
from sqlalchemy.orm import Session


def advisory_lock_key(job_id: str) -> int:
    """Return a deterministic signed 64-bit advisory-lock key for a job."""
    digest = hashlib.sha256(job_id.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, byteorder="big", signed=True)


def acquire_job_lock(db: Session, job_id: str) -> bool:
    """Try to acquire the job lock; SQLite remains a no-op for tests."""
    lock_key = advisory_lock_key(job_id)

    if "sqlite" in str(db.get_bind().url):
        return True

    result = db.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": lock_key},
    ).scalar()
    return bool(result)


def release_job_lock(db: Session, job_id: str) -> None:
    """Release the job lock; SQLite remains a no-op for tests."""
    lock_key = advisory_lock_key(job_id)

    if "sqlite" in str(db.get_bind().url):
        return

    db.execute(
        text("SELECT pg_advisory_unlock(:key)"),
        {"key": lock_key},
    )
