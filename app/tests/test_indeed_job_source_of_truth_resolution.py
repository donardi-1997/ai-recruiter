from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.candidate_ingestion import job_resolution
from app.models import IndeedJobLink, Job


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_gmail_title_fallback_does_not_adopt_unlinked_manual_vacancy():
    engine, db = _db()
    try:
        manual = Job(
            title="Analista de Automatización e IA",
            description="Manual draft",
            owner_sub="owner-1",
        )
        db.add(manual)
        db.commit()

        resolved = job_resolution.resolve_or_create_indeed_job(
            db,
            owner_sub="owner-1",
            metadata={"job_title": "Analista de Automatización e IA"},
        )

        assert resolved is None
        assert db.query(Job).count() == 1
        assert db.query(IndeedJobLink).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_gmail_title_fallback_can_use_an_already_indeed_synced_vacancy():
    engine, db = _db()
    try:
        job = Job(
            title="Country Manager Chile",
            description="Indeed description",
            indeed_description="Indeed description",
            active_description_source="indeed",
            owner_sub="owner-1",
        )
        db.add(job)
        db.flush()
        link = IndeedJobLink(
            job_id=job.id,
            owner_sub="owner-1",
            discovery_key="employer-ui:ABC123",
            external_status={"origin": "EMPLOYER_UI"},
        )
        db.add(link)
        db.commit()

        resolved = job_resolution.resolve_or_create_indeed_job(
            db,
            owner_sub="owner-1",
            metadata={"job_title": "Country Manager Chile"},
        )

        assert resolved.id == job.id
        assert db.query(Job).count() == 1
        assert db.query(IndeedJobLink).count() == 1
    finally:
        db.close()
        engine.dispose()
