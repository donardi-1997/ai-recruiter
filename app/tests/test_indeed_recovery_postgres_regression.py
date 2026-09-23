"""Regression coverage for PostgreSQL recovery queries."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Query, Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.candidate_ingestion import indeed_job_sync


def test_recovery_does_not_apply_distinct_to_event_rows_with_json(monkeypatch):
    """PostgreSQL JSON has no equality operator, so row DISTINCT is invalid."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)

    def reject_distinct(self, *expr):
        raise AssertionError(
            "PostgreSQL cannot SELECT DISTINCT full CandidateIngestionEvent rows containing JSON"
        )

    monkeypatch.setattr(Query, "distinct", reject_distinct)
    try:
        assert indeed_job_sync.recover_waiting_applications(
            db,
            owner_sub="owner-1",
        ) == 0
    finally:
        db.close()
        engine.dispose()
