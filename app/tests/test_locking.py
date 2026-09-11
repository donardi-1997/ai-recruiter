from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.deps import _advisory_lock_key, acquire_job_lock, release_job_lock


def test_lock_key_is_deterministic_and_signed_64_bit():
    key = _advisory_lock_key("job-123")
    assert key == _advisory_lock_key("job-123")
    assert -(2**63) <= key < 2**63


def test_lock_key_changes_between_jobs():
    assert _advisory_lock_key("job-a") != _advisory_lock_key("job-b")


def test_sqlite_lock_acquire_is_true_and_release_is_noop():
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as db:
        assert acquire_job_lock(db, "job-123") is True
        assert release_job_lock(db, "job-123") is None
