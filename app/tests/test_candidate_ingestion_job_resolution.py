"""Contracts for conservative candidate-ingestion job resolution."""

import pytest

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.candidate_ingestion import job_resolution
from app.models import IndeedJobLink, Job


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


def test_indeed_auto_creates_job_once_by_normalized_title():
    engine, db = _db()
    try:
        first = job_resolution.resolve_or_create_indeed_job(
            db,
            owner_sub="owner-1",
            metadata={"job_title": "Líder de Contact Center Comercial"},
        )
        second = job_resolution.resolve_or_create_indeed_job(
            db,
            owner_sub="owner-1",
            metadata={"job_title": "  lider de contact center comercial  "},
        )

        assert first is not None
        assert second is not None
        assert first.id == second.id
        assert db.query(Job).filter(Job.owner_sub == "owner-1").count() == 1

        link = db.query(IndeedJobLink).filter(IndeedJobLink.job_id == first.id).one()
        assert link.discovery_key == "title:lider de contact center comercial"
        assert link.external_status["auto_created"] is True
        assert link.external_status["origin"] == "EMAIL_AUTO_DISCOVERY"
    finally:
        db.close()
        engine.dispose()


def test_indeed_auto_creation_is_tenant_scoped():
    engine, db = _db()
    try:
        owner_a = job_resolution.resolve_or_create_indeed_job(
            db,
            owner_sub="owner-a",
            metadata={"job_title": "Country Manager Chile"},
        )
        owner_b = job_resolution.resolve_or_create_indeed_job(
            db,
            owner_sub="owner-b",
            metadata={"job_title": "Country Manager Chile"},
        )

        assert owner_a.id != owner_b.id
        assert db.query(Job).count() == 2
    finally:
        db.close()
        engine.dispose()


def test_external_indeed_posting_id_wins_over_equal_visible_titles():
    engine, db = _db()
    try:
        first = job_resolution.resolve_or_create_indeed_job(
            db,
            owner_sub="owner-1",
            metadata={
                "job_title": "Sales Manager",
                "external_job_id": "posting-A",
            },
        )
        second = job_resolution.resolve_or_create_indeed_job(
            db,
            owner_sub="owner-1",
            metadata={
                "job_title": "Sales Manager",
                "external_job_id": "posting-B",
            },
        )
        first_again = job_resolution.resolve_or_create_indeed_job(
            db,
            owner_sub="owner-1",
            metadata={
                "job_title": "Sales Manager renamed in email",
                "external_job_id": "posting-A",
            },
        )

        assert first.id != second.id
        assert first_again.id == first.id
        assert db.query(Job).filter(Job.owner_sub == "owner-1").count() == 2
    finally:
        db.close()
        engine.dispose()


def test_title_fallback_reuses_one_existing_manual_job():
    engine, db = _db()
    try:
        manual = Job(title="Analista de Automatización e IA", owner_sub="owner-1")
        db.add(manual)
        db.commit()
        db.refresh(manual)

        resolved = job_resolution.resolve_or_create_indeed_job(
            db,
            owner_sub="owner-1",
            metadata={"job_title": "Analista de Automatización e IA"},
        )

        assert resolved.id == manual.id
        assert db.query(Job).count() == 1
        link = db.query(IndeedJobLink).filter(IndeedJobLink.job_id == manual.id).one()
        assert link.external_status["auto_created"] is False
    finally:
        db.close()
        engine.dispose()


def test_title_discovery_key_preserves_meaningful_symbols():
    assert job_resolution.indeed_discovery_key(
        {"job_title": "C++ Developer"}
    ) != job_resolution.indeed_discovery_key(
        {"job_title": "C Developer"}
    )


def test_indeed_discovery_key_is_unique_per_owner_at_database_level():
    engine, db = _db()
    try:
        first = Job(title="Role A", owner_sub="owner-1")
        second = Job(title="Role B", owner_sub="owner-1")
        db.add_all([first, second])
        db.flush()
        db.add(
            IndeedJobLink(
                job_id=first.id,
                owner_sub="owner-1",
                discovery_key="title:same",
            )
        )
        db.commit()

        db.add(
            IndeedJobLink(
                job_id=second.id,
                owner_sub="owner-1",
                discovery_key="title:same",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def test_same_indeed_discovery_key_is_allowed_for_different_owners():
    engine, db = _db()
    try:
        first = Job(title="Role", owner_sub="owner-1")
        second = Job(title="Role", owner_sub="owner-2")
        db.add_all([first, second])
        db.flush()
        db.add_all(
            [
                IndeedJobLink(
                    job_id=first.id,
                    owner_sub="owner-1",
                    discovery_key="title:role",
                ),
                IndeedJobLink(
                    job_id=second.id,
                    owner_sub="owner-2",
                    discovery_key="title:role",
                ),
            ]
        )
        db.commit()

        assert db.query(IndeedJobLink).count() == 2
    finally:
        db.close()
        engine.dispose()


def test_title_discovered_job_is_enriched_when_posting_id_appears_later():
    engine, db = _db()
    try:
        first = job_resolution.resolve_or_create_indeed_job(
            db,
            owner_sub="owner-1",
            metadata={"job_title": "Country Manager Chile"},
        )
        second = job_resolution.resolve_or_create_indeed_job(
            db,
            owner_sub="owner-1",
            metadata={
                "job_title": "Country Manager Chile",
                "external_job_id": "JK123456",
            },
        )
        third = job_resolution.resolve_or_create_indeed_job(
            db,
            owner_sub="owner-1",
            metadata={
                "job_title": "Country Manager Chile updated",
                "external_job_id": "JK123456",
            },
        )

        assert first.id == second.id == third.id
        assert db.query(Job).count() == 1
        link = db.query(IndeedJobLink).filter(IndeedJobLink.job_id == first.id).one()
        assert link.discovery_key == "title:country manager chile"
        assert link.sourced_posting_id == "JK123456"
    finally:
        db.close()
        engine.dispose()
