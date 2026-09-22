"""Contracts for resetting Gmail ingestion to the current mailbox state."""

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.config import GmailOAuthSettings, GmailSettings
from app.db import Base
from app.domains.candidate_ingestion import gmail_integration, repository
from app.domains.candidate_ingestion.models import IndeedEmailResumeTask


class FakeStore:
    def __init__(self, payload):
        self.payload = dict(payload)

    def read(self):
        return dict(self.payload)

    def write(self, payload):
        self.payload = dict(payload)


class FakeMailbox:
    def __init__(self, *, email, history_id):
        self.email = email
        self.history_id = history_id

    def get_profile(self):
        return SimpleNamespace(
            email_address=self.email,
            history_id=self.history_id,
        )


def _settings():
    return GmailSettings(
        enabled=False,
        client_id="",
        client_secret="",
        refresh_token="",
        user_id="me",
        query="has:attachment",
        allowed_senders=(),
        ingestion_provider="GENERIC",
        scope="https://www.googleapis.com/auth/gmail.readonly",
        token_url="https://oauth2.googleapis.com/token",
        api_base_url="https://gmail.googleapis.com/gmail/v1",
        request_timeout_seconds=15.0,
    )


def _oauth():
    return GmailOAuthSettings(
        secret_id="/ai-recruiter/prod/gmail-oauth",
        redirect_uri="",
        frontend_return_url="https://example.invalid/integrations",
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        state_max_age_seconds=600,
    )


def _secret():
    return {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "refresh_token": "refresh-token",
        "enabled": True,
        "query": "from:indeedemail.com",
        "ingestion_provider": "INDEED",
        "authorized_owner_sub": "owner-a",
    }


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def _seed_task(db, *, owner_sub, source_account, external_id, status):
    event = repository.create_event(
        db,
        owner_sub=owner_sub,
        source="EMAIL",
        provider="INDEED",
        source_account=source_account,
        external_id=external_id,
        status="RECEIVED",
        raw_metadata={"gmail_message_id": external_id},
    )
    db.flush()
    task = IndeedEmailResumeTask(
        owner_sub=owner_sub,
        ingestion_event_id=event.id,
        candidate_name="Candidate",
        job_title="Role",
        status=status,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def test_reset_archives_only_current_owner_mailbox_and_moves_cursor_to_now():
    engine, db = _db()
    try:
        task_a = _seed_task(
            db,
            owner_sub="owner-a",
            source_account="katherine@example.com",
            external_id="gmail-a",
            status="WAITING_DOWNLOAD",
        )
        task_b = _seed_task(
            db,
            owner_sub="owner-a",
            source_account="katherine@example.com",
            external_id="gmail-b",
            status="NEEDS_HUMAN",
        )
        other_owner = _seed_task(
            db,
            owner_sub="owner-b",
            source_account="katherine@example.com",
            external_id="gmail-c",
            status="WAITING_DOWNLOAD",
        )

        result = gmail_integration.reset_mailbox_to_current(
            db,
            owner_sub="owner-a",
            settings=_settings(),
            oauth_settings=_oauth(),
            oauth_store=FakeStore(_secret()),
            mailbox_client=FakeMailbox(
                email="Katherine@example.com",
                history_id="999",
            ),
        )

        db.refresh(task_a)
        db.refresh(task_b)
        db.refresh(other_owner)

        assert result == {
            "source_account": "katherine@example.com",
            "cursor_value": "999",
            "archived": 2,
            "archived_by_status": {
                "WAITING_DOWNLOAD": 1,
                "NEEDS_HUMAN": 1,
            },
            "mode": "INCREMENTAL_FROM_NOW",
        }
        assert task_a.status == "IGNORED"
        assert task_b.status == "IGNORED"
        assert task_a.last_error_code == "HISTORICAL_BOOTSTRAP_SKIPPED"
        assert other_owner.status == "WAITING_DOWNLOAD"

        cursor = repository.get_cursor(
            db,
            owner_sub="owner-a",
            source="EMAIL",
            provider="INDEED",
            source_account="katherine@example.com",
        )
        assert cursor is not None
        assert cursor.cursor_value == "999"
    finally:
        db.close()
        engine.dispose()
