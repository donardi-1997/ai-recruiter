"""Tests for materializing ranking from already-persisted evaluations."""

import os
import tempfile
import uuid

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.domains.ranking import service as ranking_service
from app.models import Candidate, Evaluation, Job, JobCandidate, RankingItem


def _uuid() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def db_session():
    fd, path = tempfile.mkstemp(suffix=".db")
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
        os.close(fd)
        os.unlink(path)


def _forbid_evaluation(monkeypatch):
    def _must_not_evaluate(*args, **kwargs):
        raise AssertionError("materialization must not evaluate candidates")

    monkeypatch.setattr(
        ranking_service,
        "evaluate_candidate_for_job",
        _must_not_evaluate,
    )


def test_materialize_ranking_uses_persisted_evaluations_only(db_session, monkeypatch):
    job = Job(id=_uuid(), title="Backend Developer", owner_sub="test-user-123")
    first = Candidate(id=_uuid(), name="Ana", owner_sub="test-user-123")
    second = Candidate(id=_uuid(), name="Beto", owner_sub="test-user-123")
    db_session.add_all([job, first, second])
    db_session.flush()
    db_session.add_all([
        JobCandidate(job_id=job.id, candidate_id=first.id),
        JobCandidate(job_id=job.id, candidate_id=second.id),
        Evaluation(
            candidate_id=first.id,
            job_id=job.id,
            status="COMPLETED",
            match_score=90,
            recommendation="STRONG_MATCH",
            summary="x" * 120,
            strengths=[],
            gaps=[],
        ),
        Evaluation(
            candidate_id=second.id,
            job_id=job.id,
            status="COMPLETED",
            match_score=70,
            recommendation="GOOD_MATCH",
            summary="y" * 120,
            strengths=[],
            gaps=[],
        ),
    ])
    db_session.commit()
    _forbid_evaluation(monkeypatch)

    result = ranking_service.materialize_ranking_from_evaluations(
        db_session,
        job_id=job.id,
        owner_sub="test-user-123",
        scope="assigned",
    )

    assert result == {
        "job_id": job.id,
        "mode": "full",
        "scope": "assigned",
        "total_candidates": 2,
        "evaluated": 2,
        "failed": 0,
        "failures": [],
        "ranking_version": 1,
    }

    items = db_session.query(RankingItem).order_by(RankingItem.position).all()
    assert [item.candidate_id for item in items] == [first.id, second.id]
    assert [item.score for item in items] == [90.0, 70.0]


def test_materialize_ranking_preserves_completed_failed_pending_order(db_session, monkeypatch):
    job = Job(id=_uuid(), title="Platform Engineer", owner_sub="test-user-123")
    completed = Candidate(id=_uuid(), name="Zulu", owner_sub="test-user-123")
    failed = Candidate(id=_uuid(), name="Aaron", owner_sub="test-user-123")
    pending = Candidate(id=_uuid(), name="Beta", owner_sub="test-user-123")
    db_session.add_all([job, completed, failed, pending])
    db_session.flush()
    db_session.add_all([
        JobCandidate(job_id=job.id, candidate_id=completed.id),
        JobCandidate(job_id=job.id, candidate_id=failed.id),
        JobCandidate(job_id=job.id, candidate_id=pending.id),
        Evaluation(
            candidate_id=completed.id,
            job_id=job.id,
            status="COMPLETED",
            match_score=80,
            recommendation="GOOD_MATCH",
            summary="c" * 120,
            strengths=[],
            gaps=[],
        ),
        Evaluation(
            candidate_id=failed.id,
            job_id=job.id,
            status="FAILED",
            match_score=0,
            recommendation="EVALUATION_FAILED",
            summary="No fue posible completar la evaluación. Intenta nuevamente.",
            strengths=[],
            gaps=[],
            error_message="provider failed",
        ),
    ])
    db_session.commit()
    _forbid_evaluation(monkeypatch)

    result = ranking_service.materialize_ranking_from_evaluations(
        db_session,
        job_id=job.id,
        owner_sub="test-user-123",
    )

    assert result["total_candidates"] == 3
    assert result["evaluated"] == 1
    assert result["failed"] == 1
    assert result["failures"] == [
        {"candidate_id": failed.id, "error": "provider failed"}
    ]

    items = db_session.query(RankingItem).order_by(RankingItem.position).all()
    assert [item.candidate_id for item in items] == [
        completed.id,
        failed.id,
        pending.id,
    ]
    assert [item.score for item in items] == [80.0, 0.0, 0.0]
