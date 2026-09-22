"""Persistence and behavior contracts for versioned job evaluations."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.jobs import service
from app.models import Candidate, Evaluation, Job, JobCandidate, JobReevaluationTask


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def _seed_job(db: Session, *, with_candidate: bool = False) -> Job:
    job = Job(
        title="Cloud Engineer",
        description="Build AWS platforms",
        owner_sub="owner-1",
        country_code="CO",
        city="Bogota",
        employment_type="FULL_TIME",
        public_slug="cloud-engineer",
        evaluation_version=1,
        evaluation_profile={},
    )
    db.add(job)
    db.flush()
    if with_candidate:
        candidate = Candidate(
            name="Ada Candidate",
            email="ada@example.com",
            owner_sub="owner-1",
        )
        db.add(candidate)
        db.flush()
        db.add(JobCandidate(job_id=job.id, candidate_id=candidate.id))
    db.commit()
    db.refresh(job)
    return job


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


def test_job_candidate_and_evaluation_are_unique_per_logical_pair():
    job_candidate_unique_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in JobCandidate.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    evaluation_unique_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in Evaluation.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert ("job_id", "candidate_id") in job_candidate_unique_sets
    assert ("job_id", "candidate_id") in evaluation_unique_sets


def test_reevaluation_task_is_unique_per_job_and_target_version():
    table = JobReevaluationTask.__table__
    unique_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert ("job_id", "target_evaluation_version") in unique_sets


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "Senior Cloud Engineer"),
        ("description", "Build secure AWS and Kubernetes platforms"),
        (
            "evaluation_profile",
            {"required_technologies": ["AWS", "Terraform"]},
        ),
    ],
)
def test_evaluation_relevant_change_increments_version_and_schedules_once(field, value):
    engine, db = _db()
    try:
        job = _seed_job(db, with_candidate=True)
        kwargs = {field: value}

        updated = service.update_job(
            db,
            job_id=job.id,
            owner_sub="owner-1",
            **kwargs,
        )

        assert updated.evaluation_version == 2
        assert updated._evaluation_changed is True
        assert updated._reevaluation_scheduled is True
        assert updated._reevaluation_candidate_count == 1
        tasks = db.query(JobReevaluationTask).filter(JobReevaluationTask.job_id == job.id).all()
        assert len(tasks) == 1
        assert tasks[0].target_evaluation_version == 2
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("public_slug", "cloud-engineer-colombia"),
        ("published_at", datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)),
        ("country_code", "CL"),
        ("city", "Santiago"),
        ("employment_type", "CONTRACT"),
    ],
)
def test_metadata_only_change_does_not_increment_or_schedule(field, value):
    engine, db = _db()
    try:
        job = _seed_job(db, with_candidate=True)

        updated = service.update_job(
            db,
            job_id=job.id,
            owner_sub="owner-1",
            **{field: value},
        )

        assert updated.evaluation_version == 1
        assert updated._evaluation_changed is False
        assert updated._reevaluation_scheduled is False
        assert db.query(JobReevaluationTask).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_identical_normalized_content_does_not_increment_version():
    engine, db = _db()
    try:
        job = _seed_job(db, with_candidate=True)
        job.evaluation_profile = {
            "required_technologies": ["AWS", "Terraform"],
        }
        db.commit()

        updated = service.update_job(
            db,
            job_id=job.id,
            owner_sub="owner-1",
            title="  Cloud   Engineer  ",
            description=" Build   AWS platforms ",
            evaluation_profile={
                "required_technologies": [" AWS ", "Terraform"],
            },
        )

        assert updated.evaluation_version == 1
        assert updated._evaluation_changed is False
        assert db.query(JobReevaluationTask).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_version_change_without_assigned_candidates_does_not_schedule_task():
    engine, db = _db()
    try:
        job = _seed_job(db, with_candidate=False)
        updated = service.update_job(
            db,
            job_id=job.id,
            owner_sub="owner-1",
            description="Build AWS and Terraform platforms",
        )

        assert updated.evaluation_version == 2
        assert updated._evaluation_changed is True
        assert updated._reevaluation_candidate_count == 0
        assert updated._reevaluation_scheduled is False
        assert db.query(JobReevaluationTask).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_ai_description_is_saved_without_overwriting_indeed_description():
    engine, db = _db()
    try:
        job = Job(
            title="Cloud Engineer",
            description="Original Indeed description",
            indeed_description="Original Indeed description",
            ai_description=None,
            active_description_source="indeed",
            owner_sub="owner-1",
            evaluation_version=1,
            evaluation_profile={},
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        updated = service.update_job(
            db,
            job_id=job.id,
            owner_sub="owner-1",
            ai_description="AI optimized description",
            active_description_source="ai",
        )

        assert updated.indeed_description == "Original Indeed description"
        assert updated.ai_description == "AI optimized description"
        assert updated.active_description_source == "ai"
        assert updated.description == "AI optimized description"
        assert updated.evaluation_version == 2
    finally:
        db.close()
        engine.dispose()


def test_indeed_ingestion_preserves_active_ai_description_and_evaluation_version():
    engine, db = _db()
    try:
        job = Job(
            title="Cloud Engineer",
            description="AI optimized description",
            indeed_description="Indeed description v1",
            ai_description="AI optimized description",
            active_description_source="ai",
            owner_sub="owner-1",
            evaluation_version=4,
            evaluation_profile={"required_technologies": ["AWS"]},
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        updated = service.update_job(
            db,
            job_id=job.id,
            owner_sub="owner-1",
            indeed_description="Indeed description v2",
        )

        assert updated.indeed_description == "Indeed description v2"
        assert updated.ai_description == "AI optimized description"
        assert updated.active_description_source == "ai"
        assert updated.description == "AI optimized description"
        assert updated.evaluation_version == 4
        assert updated._evaluation_changed is False
    finally:
        db.close()
        engine.dispose()


def test_switching_description_source_changes_effective_evaluation_description():
    engine, db = _db()
    try:
        job = Job(
            title="Cloud Engineer",
            description="AI optimized description",
            indeed_description="Original Indeed description",
            ai_description="AI optimized description",
            active_description_source="ai",
            owner_sub="owner-1",
            evaluation_version=2,
            evaluation_profile={},
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        updated = service.update_job(
            db,
            job_id=job.id,
            owner_sub="owner-1",
            active_description_source="indeed",
        )

        assert updated.description == "Original Indeed description"
        assert updated.active_description_source == "indeed"
        assert updated.ai_description == "AI optimized description"
        assert updated.evaluation_version == 3
        assert updated._evaluation_changed is True
    finally:
        db.close()
        engine.dispose()


def test_schedule_reevaluation_is_idempotent_for_same_job_version():
    from app.domains.jobs.reevaluation import schedule_reevaluation

    engine, db = _db()
    try:
        job = _seed_job(db, with_candidate=True)
        job.evaluation_version = 4
        db.commit()

        first = schedule_reevaluation(db, job=job, owner_sub="owner-1")
        second = schedule_reevaluation(db, job=job, owner_sub="owner-1")
        db.commit()

        assert first.id == second.id
        assert db.query(JobReevaluationTask).count() == 1
    finally:
        db.close()
        engine.dispose()
