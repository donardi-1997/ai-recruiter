"""Contracts for version-aware candidate/job evaluation reuse."""

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.domains.evaluations import service
from app.models import Candidate, Evaluation, Job


def _uuid() -> str:
    return str(uuid.uuid4())


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def _seed_pair(db: Session, *, job_version: int = 1):
    candidate = Candidate(
        id=_uuid(),
        name="Ada Candidate",
        email="ada@example.com",
        owner_sub="owner-1",
    )
    job = Job(
        id=_uuid(),
        title="Cloud Engineer",
        description="Build reliable AWS platforms with Python and Terraform.",
        owner_sub="owner-1",
        evaluation_version=job_version,
    )
    db.add_all([candidate, job])
    db.commit()
    return candidate, job


def _complete_evaluation(
    db: Session,
    *,
    candidate_id: str,
    job_id: str,
    job_version: int,
    status: str = "COMPLETED",
):
    evaluation = Evaluation(
        id=_uuid(),
        candidate_id=candidate_id,
        job_id=job_id,
        job_evaluation_version=job_version,
        status=status,
        match_score=86 if status == "COMPLETED" else 0,
        recommendation="GOOD_MATCH" if status == "COMPLETED" else "EVALUATION_FAILED",
        summary=(
            "This candidate has relevant cloud engineering experience and enough documented evidence "
            "to satisfy the complete evaluation persistence contract for this test case."
            if status == "COMPLETED"
            else "No fue posible completar la evaluación. Intenta nuevamente."
        ),
        strengths=["AWS"] if status == "COMPLETED" else [],
        gaps=[],
        requirements=[],
        error_message=None if status == "COMPLETED" else "temporary",
    )
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)
    return evaluation


def _valid_llm_result():
    return {
        "status": "COMPLETED",
        "match_score": 91,
        "recommendation": "STRONG_MATCH",
        "summary": (
            "The candidate demonstrates strong evidence across the vacancy requirements, including "
            "relevant cloud delivery experience, automation practices, and technical ownership."
        ),
        "strengths": ["AWS", "Terraform"],
        "gaps": [],
        "requirements": [],
    }


def test_current_complete_evaluation_is_reused_without_retrieval_or_llm(monkeypatch):
    engine, db = _db()
    try:
        candidate, job = _seed_pair(db, job_version=4)
        existing = _complete_evaluation(
            db,
            candidate_id=candidate.id,
            job_id=job.id,
            job_version=4,
        )

        def unexpected(*args, **kwargs):
            raise AssertionError("external evaluation should not run for a current evaluation")

        import app.evaluation as evaluation_backend

        monkeypatch.setattr(evaluation_backend, "retrieve_candidate", unexpected)
        monkeypatch.setattr(evaluation_backend, "evaluate_candidate", unexpected)

        evaluation, newly_evaluated, internal_error = service.evaluate_candidate_for_job(
            db,
            candidate=candidate,
            job=job,
        )

        assert evaluation.id == existing.id
        assert newly_evaluated is False
        assert internal_error is None
    finally:
        db.close()
        engine.dispose()


def test_stale_evaluation_runs_llm_and_persists_current_job_version(monkeypatch):
    engine, db = _db()
    try:
        candidate, job = _seed_pair(db, job_version=5)
        _complete_evaluation(
            db,
            candidate_id=candidate.id,
            job_id=job.id,
            job_version=4,
        )
        calls = []

        import app.evaluation as evaluation_backend

        monkeypatch.setattr(
            evaluation_backend,
            "retrieve_candidate",
            lambda **kwargs: calls.append(("retrieve", kwargs)) or [{"content": "evidence"}],
        )
        monkeypatch.setattr(
            evaluation_backend,
            "evaluate_candidate",
            lambda **kwargs: calls.append(("evaluate", kwargs)) or _valid_llm_result(),
        )

        evaluation, newly_evaluated, internal_error = service.evaluate_candidate_for_job(
            db,
            candidate=candidate,
            job=job,
        )

        assert [name for name, _ in calls] == ["retrieve", "evaluate"]
        assert newly_evaluated is True
        assert internal_error is None
        assert evaluation.job_evaluation_version == 5
        assert evaluation.match_score == 91
    finally:
        db.close()
        engine.dispose()


def test_failed_evaluation_is_retried_even_when_job_version_matches(monkeypatch):
    engine, db = _db()
    try:
        candidate, job = _seed_pair(db, job_version=2)
        _complete_evaluation(
            db,
            candidate_id=candidate.id,
            job_id=job.id,
            job_version=2,
            status="FAILED",
        )
        calls = []

        import app.evaluation as evaluation_backend

        monkeypatch.setattr(
            evaluation_backend,
            "retrieve_candidate",
            lambda **kwargs: calls.append("retrieve") or [{"content": "evidence"}],
        )
        monkeypatch.setattr(
            evaluation_backend,
            "evaluate_candidate",
            lambda **kwargs: calls.append("evaluate") or _valid_llm_result(),
        )

        evaluation, newly_evaluated, _ = service.evaluate_candidate_for_job(
            db,
            candidate=candidate,
            job=job,
        )

        assert calls == ["retrieve", "evaluate"]
        assert newly_evaluated is True
        assert evaluation.status == "COMPLETED"
        assert evaluation.job_evaluation_version == 2
    finally:
        db.close()
        engine.dispose()


def test_force_true_reevaluates_even_current_complete_evaluation(monkeypatch):
    engine, db = _db()
    try:
        candidate, job = _seed_pair(db, job_version=3)
        _complete_evaluation(
            db,
            candidate_id=candidate.id,
            job_id=job.id,
            job_version=3,
        )
        calls = []

        import app.evaluation as evaluation_backend

        monkeypatch.setattr(
            evaluation_backend,
            "retrieve_candidate",
            lambda **kwargs: calls.append("retrieve") or [{"content": "evidence"}],
        )
        monkeypatch.setattr(
            evaluation_backend,
            "evaluate_candidate",
            lambda **kwargs: calls.append("evaluate") or _valid_llm_result(),
        )

        evaluation, newly_evaluated, _ = service.evaluate_candidate_for_job(
            db,
            candidate=candidate,
            job=job,
            force=True,
        )

        assert calls == ["retrieve", "evaluate"]
        assert newly_evaluated is True
        assert evaluation.job_evaluation_version == 3
    finally:
        db.close()
        engine.dispose()
