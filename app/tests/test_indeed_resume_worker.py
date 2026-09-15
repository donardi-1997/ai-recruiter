"""Resumable worker contracts for Indeed resume processing."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.db import Base
from app.domains.indeed.resume_models import IndeedResumeIngestion
from app.workers import indeed_resumes


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


def _seed(db, *, status="PENDING", resume_url="https://resume.invalid/ana.pdf?sig=fake"):
    candidate = models.Candidate(name="Ana Perez", email="ana@example.com", owner_sub="owner-1")
    job = models.Job(title="Country Manager", description="Lead the local operation", owner_sub="owner-1")
    db.add_all([candidate, job])
    db.flush()
    assignment = models.JobCandidate(job_id=job.id, candidate_id=candidate.id)
    db.add(assignment)
    link = models.IndeedCandidateLink(
        owner_sub="owner-1",
        candidate_id=candidate.id,
        job_id=job.id,
        asset_id="asset-1",
        source_name="Indeed",
        resume_name="ana.pdf",
        resume_url=resume_url,
    )
    db.add(link)
    db.flush()
    task = IndeedResumeIngestion(
        owner_sub="owner-1",
        candidate_link_id=link.id,
        status=status,
    )
    db.add(task)
    db.commit()
    return candidate, job, link, task


def test_dispatch_repair_marks_timestamp_only_after_queue_success(db_session, monkeypatch):
    _candidate, _job, _link, task = _seed(db_session)
    sent = []
    monkeypatch.setattr(indeed_resumes.queue, "send_indeed_resume_ingestion", lambda value: sent.append(value) or "m-1")

    count = indeed_resumes.dispatch_undispatched_resume_ingestions(db_session)
    db_session.refresh(task)

    assert count == 1
    assert sent == [task.id]
    assert task.queue_dispatched_at is not None


def test_dispatch_repair_keeps_task_undispatched_on_queue_failure(db_session, monkeypatch):
    _candidate, _job, _link, task = _seed(db_session)

    def fail(_value):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(indeed_resumes.queue, "send_indeed_resume_ingestion", fail)

    assert indeed_resumes.dispatch_undispatched_resume_ingestions(db_session) == 0
    db_session.refresh(task)
    assert task.queue_dispatched_at is None


def test_pipeline_happy_path_downloads_stores_ingests_evaluates_and_ranks(db_session, monkeypatch):
    candidate, job, _link, task = _seed(db_session)
    monkeypatch.setattr(indeed_resumes, "SessionLocal", lambda: sessionmaker(bind=db_session.get_bind())())
    monkeypatch.setattr(
        indeed_resumes.resume_download,
        "download_resume",
        lambda *_args, **_kwargs: indeed_resumes.resume_download.DownloadedResume(
            filename="ana.pdf",
            data=b"%PDF-1.7 fake",
            sha256="a" * 64,
        ),
    )
    monkeypatch.setattr(
        indeed_resumes.storage,
        "write_canonical_candidate_document",
        lambda **_kwargs: type("Write", (), {"key": f"documents/cv-{candidate.id}.pdf", "changed": True})(),
    )
    monkeypatch.setattr(
        indeed_resumes.ingestion,
        "start_indeed_resume_ingestion",
        lambda *_args: ("bedrock-1", "STARTING"),
    )
    monkeypatch.setattr(indeed_resumes.ingestion, "get_ingestion_status", lambda _job_id: "COMPLETE")
    evaluated = []
    monkeypatch.setattr(
        indeed_resumes.evaluations_service,
        "evaluate_candidate_for_owner",
        lambda _db, **kwargs: (
            evaluated.append(kwargs) or type("Evaluation", (), {"status": "COMPLETED"})(),
            True,
            None,
        ),
    )
    ranked = []
    monkeypatch.setattr(
        indeed_resumes.ranking_service,
        "materialize_ranking_from_evaluations",
        lambda _db, **kwargs: ranked.append(kwargs) or {"ranking_version": 7},
    )
    monkeypatch.setattr(indeed_resumes.time, "sleep", lambda _seconds: None)

    indeed_resumes.process_resume_ingestion(task.id)

    with sessionmaker(bind=db_session.get_bind())() as check:
        persisted = check.query(IndeedResumeIngestion).filter_by(id=task.id).one()
        assert persisted.status == "COMPLETED"
        assert persisted.resume_sha256 == "a" * 64
        assert persisted.canonical_s3_key == f"documents/cv-{candidate.id}.pdf"
        assert persisted.bedrock_ingestion_job_id == "bedrock-1"
        assert persisted.completed_at is not None
    assert evaluated == [{"candidate_id": candidate.id, "job_id": job.id, "owner_sub": "owner-1"}]
    assert ranked == [{"job_id": job.id, "owner_sub": "owner-1", "scope": "assigned"}]


def test_resume_from_ranking_checkpoint_does_not_download_or_ingest(db_session, monkeypatch):
    candidate, job, _link, task = _seed(db_session, status="RANKING")
    task.resume_sha256 = "a" * 64
    task.canonical_s3_key = f"documents/cv-{candidate.id}.pdf"
    task.bedrock_ingestion_job_id = "bedrock-1"
    db_session.commit()
    monkeypatch.setattr(indeed_resumes, "SessionLocal", lambda: sessionmaker(bind=db_session.get_bind())())
    monkeypatch.setattr(indeed_resumes.resume_download, "download_resume", lambda *_a, **_k: pytest.fail("must not redownload"))
    monkeypatch.setattr(indeed_resumes.ingestion, "get_ingestion_status", lambda *_a, **_k: pytest.fail("must not reingest"))
    monkeypatch.setattr(indeed_resumes.evaluations_service, "evaluate_candidate_for_owner", lambda *_a, **_k: pytest.fail("must not reevaluate"))
    ranked = []
    monkeypatch.setattr(
        indeed_resumes.ranking_service,
        "materialize_ranking_from_evaluations",
        lambda _db, **kwargs: ranked.append(kwargs) or {"ranking_version": 9},
    )

    indeed_resumes.process_resume_ingestion(task.id)

    assert ranked == [{"job_id": job.id, "owner_sub": "owner-1", "scope": "assigned"}]


def test_missing_resume_url_is_terminal_public_safe_failure(db_session, monkeypatch):
    _candidate, _job, _link, task = _seed(db_session, resume_url=None)
    monkeypatch.setattr(indeed_resumes, "SessionLocal", lambda: sessionmaker(bind=db_session.get_bind())())

    indeed_resumes.process_resume_ingestion(task.id)

    with sessionmaker(bind=db_session.get_bind())() as check:
        persisted = check.query(IndeedResumeIngestion).filter_by(id=task.id).one()
        assert persisted.status == "FAILED"
        assert persisted.last_error_code == "RESUME_URL_MISSING"
        assert "http" not in (persisted.last_error_message or "").lower()


def test_failed_bedrock_ingestion_is_terminal_and_skips_evaluation(db_session, monkeypatch):
    _candidate, _job, _link, task = _seed(db_session, status="STORED")
    task.resume_sha256 = "b" * 64
    task.canonical_s3_key = "documents/cv-x.pdf"
    db_session.commit()
    monkeypatch.setattr(indeed_resumes, "SessionLocal", lambda: sessionmaker(bind=db_session.get_bind())())
    monkeypatch.setattr(indeed_resumes.ingestion, "start_indeed_resume_ingestion", lambda *_a: ("bedrock-fail", "STARTING"))
    monkeypatch.setattr(indeed_resumes.ingestion, "get_ingestion_status", lambda _id: "FAILED")
    monkeypatch.setattr(indeed_resumes.evaluations_service, "evaluate_candidate_for_owner", lambda *_a, **_k: pytest.fail("must not evaluate"))

    indeed_resumes.process_resume_ingestion(task.id)

    with sessionmaker(bind=db_session.get_bind())() as check:
        persisted = check.query(IndeedResumeIngestion).filter_by(id=task.id).one()
        assert persisted.status == "FAILED"
        assert persisted.last_error_code == "BEDROCK_INGESTION_FAILED"


def test_fifth_unexpected_failure_marks_retry_exhausted_and_leaves_message_for_dlq(db_session, monkeypatch):
    _candidate, _job, _link, task = _seed(db_session)
    deleted = []
    monkeypatch.setattr(indeed_resumes, "SessionLocal", lambda: sessionmaker(bind=db_session.get_bind())())
    monkeypatch.setattr(indeed_resumes, "process_resume_ingestion", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(indeed_resumes.queue, "delete_message", lambda value: deleted.append(value))
    message = type(
        "Message",
        (),
        {"identifier": task.id, "receipt_handle": "rh", "receive_count": 5},
    )()

    indeed_resumes.handle_message(message)

    with sessionmaker(bind=db_session.get_bind())() as check:
        persisted = check.query(IndeedResumeIngestion).filter_by(id=task.id).one()
        assert persisted.status == "FAILED"
        assert persisted.last_error_code == "RETRY_EXHAUSTED"
    assert deleted == []
