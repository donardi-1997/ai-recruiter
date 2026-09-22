"""Resumable worker contracts for provider-neutral candidate ingestion."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.db import Base
from app.domains.candidate_ingestion.models import (
    CandidateIngestionDocument,
    CandidateIngestionEvent,
)
from app.workers import candidate_ingestions


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed(db, *, subject="New application for Country Manager Chile", with_job=True):
    job = None
    if with_job:
        job = models.Job(
            title="Country Manager Chile",
            description="Lead the local operation",
            owner_sub="owner-1",
        )
        db.add(job)
        db.flush()
    event = CandidateIngestionEvent(
        owner_sub="owner-1",
        source="EMAIL",
        provider="INDEED",
        source_account="personal@example.com",
        external_id="gmail-1",
        status="STORED",
        raw_metadata={"subject": subject, "sender": "alerts@indeed.com"},
    )
    db.add(event)
    db.flush()
    document = CandidateIngestionDocument(
        ingestion_event_id=event.id,
        filename="ana.pdf",
        content_type="application/pdf",
        size_bytes=7,
        source_s3_key=f"candidate-ingestion/{event.id}/source/a/ana.pdf",
        document_sha256="a" * 64,
        status="STORED",
    )
    db.add(document)
    db.commit()
    return event, document, job


def test_dispatch_repair_marks_timestamp_only_after_queue_success(db_session, monkeypatch):
    event, _document, _job = _seed(db_session)
    sent = []
    monkeypatch.setattr(
        candidate_ingestions.queue,
        "send_candidate_ingestion",
        lambda value: sent.append(value) or "m-1",
    )

    count = candidate_ingestions.dispatch_undispatched_ingestions(db_session)
    db_session.refresh(event)

    assert count == 1
    assert sent == [event.id]
    assert event.queue_dispatched_at is not None


def test_pipeline_happy_path_parses_dedupes_assigns_ingests_evaluates_and_ranks(db_session, monkeypatch):
    event, document, job = _seed(db_session)
    monkeypatch.setattr(
        candidate_ingestions,
        "SessionLocal",
        lambda: sessionmaker(bind=db_session.get_bind())(),
    )
    monkeypatch.setattr(
        candidate_ingestions.storage,
        "read_staging_object",
        lambda key: b"pdfdata",
    )
    monkeypatch.setattr(
        candidate_ingestions.documents,
        "extract_document",
        lambda data, filename: SimpleNamespace(
            filename=filename,
            display_name="Ana Perez",
            email="ana@example.com",
            phone="+57 300 111 2233",
            sha256="a" * 64,
        ),
    )
    monkeypatch.setattr(
        candidate_ingestions.storage,
        "write_canonical_candidate_document",
        lambda **kwargs: SimpleNamespace(
            key=f"documents/cv-{kwargs['candidate_id']}.pdf",
            changed=True,
        ),
    )
    monkeypatch.setattr(
        candidate_ingestions.ingestion,
        "start_ingestion",
        lambda **kwargs: ("bedrock-1", "STARTING"),
    )
    monkeypatch.setattr(
        candidate_ingestions.ingestion,
        "get_ingestion_status",
        lambda _job_id: "COMPLETE",
    )
    evaluated = []
    monkeypatch.setattr(
        candidate_ingestions.evaluations_service,
        "evaluate_candidate_for_owner",
        lambda _db, **kwargs: (
            evaluated.append(kwargs)
            or SimpleNamespace(status="COMPLETED", error_message=None),
            True,
            None,
        ),
    )
    ranked = []
    monkeypatch.setattr(
        candidate_ingestions.ranking_service,
        "materialize_ranking_from_evaluations",
        lambda _db, **kwargs: ranked.append(kwargs) or {"ranking_version": 1},
    )
    monkeypatch.setattr(candidate_ingestions.time, "sleep", lambda _seconds: None)

    outcome = candidate_ingestions.process_ingestion_event(event.id)

    with sessionmaker(bind=db_session.get_bind())() as check:
        persisted = check.query(CandidateIngestionEvent).filter_by(id=event.id).one()
        persisted_document = check.query(CandidateIngestionDocument).filter_by(id=document.id).one()
        assert outcome == "COMPLETED"
        assert persisted.status == "COMPLETED"
        assert persisted.candidate_id is not None
        assert persisted.job_id == job.id
        assert persisted.bedrock_ingestion_job_id == "bedrock-1"
        assert persisted_document.canonical_s3_key.endswith(".pdf")
        assert persisted.completed_at is not None
        assignment = (
            check.query(models.JobCandidate)
            .filter_by(job_id=job.id, candidate_id=persisted.candidate_id)
            .one()
        )
        assert assignment is not None
    assert evaluated[0]["job_id"] == job.id
    assert ranked == [{"job_id": job.id, "owner_sub": "owner-1", "scope": "assigned"}]


def test_unresolved_job_keeps_candidate_and_routes_to_needs_review(db_session, monkeypatch):
    event, _document, _job = _seed(
        db_session,
        subject="New application",
        with_job=False,
    )
    monkeypatch.setattr(
        candidate_ingestions,
        "SessionLocal",
        lambda: sessionmaker(bind=db_session.get_bind())(),
    )
    monkeypatch.setattr(candidate_ingestions.storage, "read_staging_object", lambda _key: b"pdfdata")
    monkeypatch.setattr(
        candidate_ingestions.documents,
        "extract_document",
        lambda data, filename: SimpleNamespace(
            filename=filename,
            display_name="Ana Perez",
            email="ana@example.com",
            phone=None,
            sha256="a" * 64,
        ),
    )
    monkeypatch.setattr(
        candidate_ingestions.storage,
        "write_canonical_candidate_document",
        lambda **kwargs: SimpleNamespace(key="documents/cv-ana.pdf", changed=True),
    )
    monkeypatch.setattr(
        candidate_ingestions.ingestion,
        "start_ingestion",
        lambda **_kwargs: pytest.fail("must not ingest without resolved job"),
    )

    outcome = candidate_ingestions.process_ingestion_event(event.id)

    with sessionmaker(bind=db_session.get_bind())() as check:
        persisted = check.query(CandidateIngestionEvent).filter_by(id=event.id).one()
        assert outcome == "NEEDS_REVIEW"
        assert persisted.status == "NEEDS_REVIEW"
        assert persisted.candidate_id is not None
        assert persisted.job_id is None
        assert persisted.last_error_code == "JOB_UNRESOLVED"


def test_prelinked_candidate_is_reused_for_reconciled_resume(db_session, monkeypatch):
    event, document, job = _seed(db_session)
    candidate = models.Candidate(
        name="Existing Candidate",
        email=None,
        owner_sub="owner-1",
        metadata_={},
    )
    db_session.add(candidate)
    db_session.flush()
    event.candidate_id = candidate.id
    event.job_id = job.id
    event.raw_metadata = {
        "resume_agent_lookup_only": True,
        "candidate_name": candidate.name,
        "job_title": job.title,
    }
    db_session.commit()

    monkeypatch.setattr(
        candidate_ingestions.storage,
        "read_staging_object",
        lambda _key: b"pdfdata",
    )
    monkeypatch.setattr(
        candidate_ingestions.documents,
        "extract_document",
        lambda data, filename: SimpleNamespace(
            filename=filename,
            display_name="Different Parsed Name",
            email=None,
            phone=None,
            sha256="a" * 64,
        ),
    )
    monkeypatch.setattr(
        candidate_ingestions.candidate_identity,
        "resolve_or_create_candidate",
        lambda *args, **kwargs: pytest.fail("prelinked candidate must be reused"),
    )
    monkeypatch.setattr(
        candidate_ingestions.storage,
        "write_canonical_candidate_document",
        lambda **kwargs: SimpleNamespace(
            key=f"documents/cv-{kwargs['candidate_id']}.pdf",
            changed=True,
        ),
    )

    outcome = candidate_ingestions._prepare_document(db_session, event)

    db_session.refresh(event)
    db_session.refresh(document)
    assert outcome is None
    assert event.candidate_id == candidate.id
    assert event.job_id == job.id
    assert event.status == "INGESTING"
    assert document.canonical_s3_key == f"documents/cv-{candidate.id}.pdf"
    assignment = (
        db_session.query(models.JobCandidate)
        .filter_by(job_id=job.id, candidate_id=candidate.id)
        .one()
    )
    assert assignment is not None


def test_multiple_resume_documents_route_to_needs_review_without_guessing(db_session, monkeypatch):
    event, _document, _job = _seed(db_session)
    db_session.add(
        CandidateIngestionDocument(
            ingestion_event_id=event.id,
            filename="second.pdf",
            content_type="application/pdf",
            size_bytes=8,
            source_s3_key=f"candidate-ingestion/{event.id}/source/b/second.pdf",
            document_sha256="b" * 64,
            status="STORED",
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        candidate_ingestions,
        "SessionLocal",
        lambda: sessionmaker(bind=db_session.get_bind())(),
    )
    monkeypatch.setattr(
        candidate_ingestions.storage,
        "read_staging_object",
        lambda _key: pytest.fail("must not guess between documents"),
    )

    outcome = candidate_ingestions.process_ingestion_event(event.id)

    with sessionmaker(bind=db_session.get_bind())() as check:
        persisted = check.query(CandidateIngestionEvent).filter_by(id=event.id).one()
        assert outcome == "NEEDS_REVIEW"
        assert persisted.last_error_code == "MULTIPLE_RESUME_ATTACHMENTS"
