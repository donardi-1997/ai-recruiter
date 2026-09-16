"""Persistence contracts for versioned job evaluations."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.models import Evaluation, Job, JobReevaluationTask


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_job_defaults_include_evaluation_version_profile_and_updated_at():
    engine, db = _db()
    try:
        job = Job(title="Cloud Engineer", owner_sub="owner-1")
        db.add(job)
        db.commit()
        db.refresh(job)

        assert job.evaluation_version == 1
        assert job.evaluation_profile == {}
        assert job.updated_at is not None
    finally:
        db.close()
        engine.dispose()


def test_evaluation_persists_source_job_version():
    engine, db = _db()
    try:
        job = Job(title="Cloud Engineer", owner_sub="owner-1")
        db.add(job)
        db.flush()

        evaluation = Evaluation(
            candidate_id="00000000-0000-0000-0000-000000000001",
            job_id=job.id,
            job_evaluation_version=3,
            status="COMPLETED",
            match_score=80,
        )
        assert evaluation.job_evaluation_version == 3
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def test_reevaluation_task_is_unique_per_job_and_target_version():
    table = JobReevaluationTask.__table__
    unique_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert ("job_id", "target_evaluation_version") in unique_sets
