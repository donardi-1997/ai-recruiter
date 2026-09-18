"""Contracts for discovering Indeed applications from Gmail notifications."""

from __future__ import annotations

import base64
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.candidate_ingestion.models import IndeedEmailResumeTask
from app.models import Job


def _b64url(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _message(
    *,
    message_id: str = "gmail-indeed-1",
    sender: str = "Indeed <conversation-abc@indeedemail.com>",
    candidate_name: str = "Ana Perez",
    job_title: str = "Country Manager Chile",
    resume_url: str = "https://employers.indeed.com/resume/ana-perez",
    include_link: bool = True,
    external_job_id: str | None = None,
):
    link = f'<a href="{resume_url}">Ver CV</a>' if include_link else ""
    job_link = (
        f'<a href="https://www.indeed.com/viewjob?jk={external_job_id}">Ver vacante</a>'
        if external_job_id
        else ""
    )
    html = (
        "<html><body>"
        f"<p>{candidate_name} se postulo para {job_title}</p>"
        f"{job_link}"
        f"{link}"
        "</body></html>"
    )
    return {
        "id": message_id,
        "threadId": f"thread-{message_id}",
        "historyId": "700",
        "internalDate": "1789574400000",
        "payload": {
            "mimeType": "text/html",
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": f"{candidate_name} se postulo"},
            ],
            "body": {"data": _b64url(html)},
        },
    }


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_valid_indeed_email_creates_download_task_without_persisting_resume_url():
    from app.domains.candidate_ingestion.indeed_email_service import discover_indeed_email

    engine, db = _db()
    try:
        job = Job(title="Country Manager Chile", owner_sub="owner-1")
        db.add(job)
        db.commit()

        result = discover_indeed_email(
            db,
            owner_sub="owner-1",
            source_account="katherine@example.com",
            raw_message=_message(),
        )

        assert result is not None
        assert result.created is True
        assert result.event.status == "RECEIVED"
        assert result.event.last_error_code == "RESUME_DOWNLOAD_PENDING"
        assert result.task is not None
        assert result.task.status == "WAITING_DOWNLOAD"
        assert result.task.candidate_name == "Ana Perez"
        assert result.task.job_title == "Country Manager Chile"
        assert result.event.job_id == job.id
        assert result.task.job_id == job.id

        serialized = json.dumps(result.event.raw_metadata, sort_keys=True)
        assert "resume_url" not in serialized
        assert "employers.indeed.com" not in serialized
        assert result.event.raw_metadata["gmail_message_id"] == "gmail-indeed-1"
        assert result.event.raw_metadata["sender"] == "conversation-abc@indeedemail.com"
        assert result.event.raw_metadata["candidate_name"] == "Ana Perez"
        assert result.event.raw_metadata["job_title"] == "Country Manager Chile"
    finally:
        db.close()
        engine.dispose()


def test_ambiguous_manual_jobs_create_one_dedicated_indeed_job():
    from app.domains.candidate_ingestion.indeed_email_service import discover_indeed_email
    from app.models import IndeedJobLink

    engine, db = _db()
    try:
        manual_a = Job(title="Sales Manager", owner_sub="owner-1")
        manual_b = Job(title="Sales Manager", owner_sub="owner-1")
        db.add_all([manual_a, manual_b])
        db.commit()

        result = discover_indeed_email(
            db,
            owner_sub="owner-1",
            source_account="katherine@example.com",
            raw_message=_message(job_title="Sales Manager"),
        )

        assert result is not None
        assert result.task is not None
        assert result.event.job_id is not None
        assert result.task.job_id == result.event.job_id
        assert result.event.job_id not in {manual_a.id, manual_b.id}
        assert result.task.status == "WAITING_DOWNLOAD"
        assert db.query(Job).filter(Job.owner_sub == "owner-1").count() == 3

        link = (
            db.query(IndeedJobLink)
            .filter(IndeedJobLink.job_id == result.event.job_id)
            .one()
        )
        assert link.discovery_key == "title:sales manager"
        assert link.external_status["auto_created"] is True
    finally:
        db.close()
        engine.dispose()


def test_missing_resume_link_is_needs_review_without_task():
    from app.domains.candidate_ingestion.indeed_email_service import discover_indeed_email

    engine, db = _db()
    try:
        result = discover_indeed_email(
            db,
            owner_sub="owner-1",
            source_account="katherine@example.com",
            raw_message=_message(include_link=False),
        )

        assert result is not None
        assert result.created is True
        assert result.task is None
        assert result.event.status == "NEEDS_REVIEW"
        assert result.event.last_error_code == "INDEED_EMAIL_INVALID"
        assert db.query(IndeedEmailResumeTask).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_external_resume_link_is_needs_review_and_url_is_never_persisted():
    from app.domains.candidate_ingestion.indeed_email_service import discover_indeed_email

    engine, db = _db()
    try:
        result = discover_indeed_email(
            db,
            owner_sub="owner-1",
            source_account="katherine@example.com",
            raw_message=_message(resume_url="https://indeed.com.evil.example/steal"),
        )

        assert result is not None
        assert result.task is None
        assert result.event.status == "NEEDS_REVIEW"
        assert result.event.last_error_code == "INDEED_RESUME_LINK_INVALID"
        persisted = json.dumps(result.event.raw_metadata, sort_keys=True)
        assert "evil.example" not in persisted
        assert "evil.example" not in str(result.event.last_error_message or "")
    finally:
        db.close()
        engine.dispose()


def test_repeated_message_reuses_same_event_and_task():
    from app.domains.candidate_ingestion.indeed_email_service import discover_indeed_email

    engine, db = _db()
    try:
        message = _message()
        first = discover_indeed_email(
            db,
            owner_sub="owner-1",
            source_account="katherine@example.com",
            raw_message=message,
        )
        second = discover_indeed_email(
            db,
            owner_sub="owner-1",
            source_account="katherine@example.com",
            raw_message=message,
        )

        assert first is not None and second is not None
        assert first.event.id == second.event.id
        assert first.task is not None and second.task is not None
        assert first.task.id == second.task.id
        assert second.created is False
        assert db.query(IndeedEmailResumeTask).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_non_indeed_sender_falls_through_without_creating_event():
    from app.domains.candidate_ingestion.indeed_email_service import discover_indeed_email
    from app.domains.candidate_ingestion.models import CandidateIngestionEvent

    engine, db = _db()
    try:
        result = discover_indeed_email(
            db,
            owner_sub="owner-1",
            source_account="katherine@example.com",
            raw_message=_message(sender="Recruiter <person@example.com>"),
        )

        assert result is None
        assert db.query(CandidateIngestionEvent).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_new_indeed_title_auto_creates_job_and_other_messages_reuse_it():
    from app.domains.candidate_ingestion.indeed_email_service import discover_indeed_email

    engine, db = _db()
    try:
        first = discover_indeed_email(
            db,
            owner_sub="owner-1",
            source_account="katherine@example.com",
            raw_message=_message(
                message_id="gmail-auto-1",
                candidate_name="Ana Perez",
                job_title="Líder de Contact Center Comercial",
            ),
        )
        second = discover_indeed_email(
            db,
            owner_sub="owner-1",
            source_account="katherine@example.com",
            raw_message=_message(
                message_id="gmail-auto-2",
                candidate_name="Luis Gomez",
                job_title="lider de contact center comercial",
            ),
        )

        assert first.event.job_id is not None
        assert second.event.job_id == first.event.job_id
        assert first.task.job_id == first.event.job_id
        assert second.task.job_id == first.event.job_id
        assert db.query(Job).filter(Job.owner_sub == "owner-1").count() == 1
    finally:
        db.close()
        engine.dispose()


def test_distinct_external_posting_ids_create_distinct_jobs_even_with_same_title():
    from app.domains.candidate_ingestion.indeed_email_service import discover_indeed_email

    engine, db = _db()
    try:
        first = discover_indeed_email(
            db,
            owner_sub="owner-1",
            source_account="katherine@example.com",
            raw_message=_message(
                message_id="gmail-posting-a",
                candidate_name="Ana Perez",
                job_title="Sales Manager",
                external_job_id="POSTING_A_123",
            ),
        )
        second = discover_indeed_email(
            db,
            owner_sub="owner-1",
            source_account="katherine@example.com",
            raw_message=_message(
                message_id="gmail-posting-b",
                candidate_name="Luis Gomez",
                job_title="Sales Manager",
                external_job_id="POSTING_B_456",
            ),
        )

        assert first.event.job_id != second.event.job_id
        assert db.query(Job).filter(Job.owner_sub == "owner-1").count() == 2
        assert first.event.raw_metadata["external_job_id"] == "POSTING_A_123"
        assert second.event.raw_metadata["external_job_id"] == "POSTING_B_456"
    finally:
        db.close()
        engine.dispose()
