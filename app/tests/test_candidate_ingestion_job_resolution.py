"""Contracts for conservative candidate-ingestion job resolution."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.candidate_ingestion import job_resolution
from app.models import Job


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_explicit_owned_job_id_wins():
    engine, db = _db()
    try:
        job = Job(title="Country Manager Chile", owner_sub="owner-1")
        db.add(job)
        db.commit()
        db.refresh(job)

        resolved = job_resolution.resolve_job(
            db,
            owner_sub="owner-1",
            explicit_job_id=job.id,
            metadata={"subject": "Something unrelated"},
        )
        assert resolved.id == job.id
    finally:
        db.close()
        engine.dispose()


def test_subject_resolves_unique_owned_job_title_without_ai_guessing():
    engine, db = _db()
    try:
        job = Job(title="Country Manager Chile", owner_sub="owner-1")
        db.add(job)
        db.commit()

        resolved = job_resolution.resolve_job(
            db,
            owner_sub="owner-1",
            explicit_job_id=None,
            metadata={"subject": "New application for Country Manager Chile"},
        )
        assert resolved.id == job.id
    finally:
        db.close()
        engine.dispose()


def test_extracted_job_title_exact_match_precedes_subject_fallback():
    engine, db = _db()
    try:
        expected = Job(
            title="Analista de Automatización e IA",
            owner_sub="owner-1",
        )
        fallback = Job(title="Country Manager Chile", owner_sub="owner-1")
        db.add_all([expected, fallback])
        db.commit()

        resolved = job_resolution.resolve_job(
            db,
            owner_sub="owner-1",
            explicit_job_id=None,
            metadata={
                "job_title": "Analista de Automatización e IA",
                "subject": "New application for Country Manager Chile",
            },
        )

        assert resolved.id == expected.id
    finally:
        db.close()
        engine.dispose()


def test_duplicate_exact_job_titles_are_ambiguous_without_subject_fallback():
    engine, db = _db()
    try:
        db.add_all(
            [
                Job(title="Sales Manager", owner_sub="owner-1"),
                Job(title="Sales Manager", owner_sub="owner-1"),
                Job(title="Country Manager Chile", owner_sub="owner-1"),
            ]
        )
        db.commit()

        resolved = job_resolution.resolve_job(
            db,
            owner_sub="owner-1",
            explicit_job_id=None,
            metadata={
                "job_title": "Sales Manager",
                "subject": "New application for Country Manager Chile",
            },
        )

        assert resolved is None
    finally:
        db.close()
        engine.dispose()


def test_extracted_job_title_never_resolves_other_tenants_job():
    engine, db = _db()
    try:
        db.add(Job(title="Country Manager Chile", owner_sub="other-owner"))
        db.commit()

        resolved = job_resolution.resolve_job(
            db,
            owner_sub="owner-1",
            explicit_job_id=None,
            metadata={
                "job_title": "Country Manager Chile",
                "subject": "Indeed application",
            },
        )

        assert resolved is None
    finally:
        db.close()
        engine.dispose()


def test_ambiguous_or_missing_title_returns_none():
    engine, db = _db()
    try:
        db.add_all(
            [
                Job(title="Sales Manager", owner_sub="owner-1"),
                Job(title="Manager", owner_sub="owner-1"),
            ]
        )
        db.commit()

        ambiguous = job_resolution.resolve_job(
            db,
            owner_sub="owner-1",
            explicit_job_id=None,
            metadata={"subject": "Candidate for Sales Manager / Manager"},
        )
        missing = job_resolution.resolve_job(
            db,
            owner_sub="owner-1",
            explicit_job_id=None,
            metadata={"subject": "New candidate"},
        )

        assert ambiguous is None
        assert missing is None
    finally:
        db.close()
        engine.dispose()


def test_subject_never_resolves_other_tenants_job():
    engine, db = _db()
    try:
        db.add(Job(title="Country Manager Chile", owner_sub="other-owner"))
        db.commit()

        resolved = job_resolution.resolve_job(
            db,
            owner_sub="owner-1",
            explicit_job_id=None,
            metadata={"subject": "New application for Country Manager Chile"},
        )
        assert resolved is None
    finally:
        db.close()
        engine.dispose()
