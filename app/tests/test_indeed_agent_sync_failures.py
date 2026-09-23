from __future__ import annotations

import pytest

from app.domains.candidate_ingestion import indeed_agent_sync
from app.domains.candidate_ingestion.gmail_integration import GmailRemoteError


class FakeDb:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


def _gmail_result(**overrides):
    payload = {
        "mode": "INCREMENTAL",
        "discovered": 0,
        "created": 0,
        "existing": 0,
        "needs_review": 0,
        "skipped": 0,
        "cursor_value": "123",
    }
    payload.update(overrides)
    return payload


def test_sync_preserves_safe_gmail_failure_code(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(
        indeed_agent_sync.indeed_job_sync,
        "recover_waiting_applications",
        lambda *args, **kwargs: 0,
    )

    def fail_gmail(*args, **kwargs):
        raise GmailRemoteError(
            "GMAIL_TOKEN_REFRESH_REJECTED: vuelve a conectar la cuenta de Gmail."
        )

    monkeypatch.setattr(indeed_agent_sync.gmail_integration, "sync_mailbox", fail_gmail)

    with pytest.raises(indeed_agent_sync.ResumeSyncStageError) as caught:
        indeed_agent_sync.sync_one_page(db, owner_sub="owner-a")

    assert caught.value.code == "GMAIL_TOKEN_REFRESH_REJECTED"
    assert db.rollbacks == 1


def test_sync_classifies_recovery_failure_before_gmail(monkeypatch):
    db = FakeDb()
    gmail_calls = 0

    def fail_recovery(*args, **kwargs):
        raise RuntimeError("legacy row broke recovery")

    def gmail(*args, **kwargs):
        nonlocal gmail_calls
        gmail_calls += 1
        return _gmail_result()

    monkeypatch.setattr(
        indeed_agent_sync.indeed_job_sync,
        "recover_waiting_applications",
        fail_recovery,
    )
    monkeypatch.setattr(indeed_agent_sync.gmail_integration, "sync_mailbox", gmail)

    with pytest.raises(indeed_agent_sync.ResumeSyncStageError) as caught:
        indeed_agent_sync.sync_one_page(db, owner_sub="owner-a")

    assert caught.value.code == "RESUME_SYNC_RECOVERY_FAILED"
    assert db.rollbacks == 1
    assert gmail_calls == 0


def test_sync_classifies_reconcile_failure(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(
        indeed_agent_sync.indeed_job_sync,
        "recover_waiting_applications",
        lambda *args, **kwargs: 0,
    )
    monkeypatch.setattr(
        indeed_agent_sync.gmail_integration,
        "sync_mailbox",
        lambda *args, **kwargs: _gmail_result(mode="FULL"),
    )
    monkeypatch.setattr(
        indeed_agent_sync,
        "reconcile_existing_indeed_candidates",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("bad legacy candidate")),
    )

    with pytest.raises(indeed_agent_sync.ResumeSyncStageError) as caught:
        indeed_agent_sync.sync_one_page(db, owner_sub="owner-a")

    assert caught.value.code == "RESUME_SYNC_RECONCILE_FAILED"
    assert db.rollbacks == 1
