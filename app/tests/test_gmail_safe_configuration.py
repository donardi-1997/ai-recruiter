"""Safety contracts for Gmail candidate-ingestion mailbox configuration."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.config as config
import app.models  # noqa: F401
from app.db import Base
from app.domains.candidate_ingestion import gmail_integration


class NeverCalledMailbox:
    def get_profile(self):
        raise AssertionError("unsafe configuration must fail before Gmail is called")


def _settings(monkeypatch, *, query="has:attachment", allowed_senders=""):
    monkeypatch.setenv("GMAIL_ENABLED", "true")
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("GMAIL_QUERY", query)
    monkeypatch.setenv("GMAIL_ALLOWED_SENDERS", allowed_senders)
    return config.get_gmail_settings()


def test_enabled_ingestion_rejects_broad_attachment_scan_without_sender_allowlist(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            with pytest.raises(gmail_integration.GmailUnsafeConfiguration):
                gmail_integration.sync_mailbox(
                    db,
                    owner_sub="owner-1",
                    settings=_settings(monkeypatch),
                    mailbox_client=NeverCalledMailbox(),
                )
    finally:
        engine.dispose()


def test_sender_allowlist_makes_default_attachment_query_acceptable(monkeypatch):
    settings = _settings(
        monkeypatch,
        allowed_senders="alerts@example.com",
    )
    assert gmail_integration.is_safe_mailbox_filter(settings) is True


def test_restrictive_from_query_can_be_used_without_separate_allowlist(monkeypatch):
    settings = _settings(
        monkeypatch,
        query="from:(alerts@example.com) has:attachment",
    )
    assert gmail_integration.is_safe_mailbox_filter(settings) is True


def test_indeed_link_discovery_query_is_safe_without_attachment_or_allowlist(monkeypatch):
    settings = _settings(
        monkeypatch,
        query="from:indeedemail.com",
        allowed_senders="",
    )
    assert settings.query == "from:indeedemail.com"
    assert settings.allowed_senders == ()
    assert "has:attachment" not in settings.query
    assert gmail_integration.is_safe_mailbox_filter(settings) is True
