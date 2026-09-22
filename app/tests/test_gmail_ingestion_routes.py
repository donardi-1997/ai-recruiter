"""HTTP contracts for configurable Gmail candidate ingestion."""

import pytest
from fastapi.testclient import TestClient

from app.deps import get_current_user, get_db
from app.domains.candidate_ingestion import gmail_integration, indeed_email_agent_service
from app.main import app


@pytest.fixture()
def api():
    principal = {"sub": "owner-a", "email": "recruiter@example.com"}

    def override_db():
        yield object()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: dict(principal)
    with TestClient(app) as client:
        yield client, principal
    app.dependency_overrides.clear()


def test_gmail_status_never_exposes_oauth_secrets(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(
        gmail_integration,
        "integration_status",
        lambda *, owner_sub: {
            "enabled": True,
            "configured": True,
            "provider": "INDEED",
        },
    )

    response = client.get("/api/integrations/gmail/status")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "configured": True,
        "provider": "INDEED",
    }
    serialized = response.text.casefold()
    assert "client_secret" not in serialized
    assert "refresh_token" not in serialized
    assert "password" not in serialized


def test_gmail_sync_uses_authenticated_owner(api, monkeypatch):
    client, principal = api
    calls = {}

    def fake_sync(db, *, owner_sub):
        calls.update(db=db, owner_sub=owner_sub)
        return {
            "mode": "FULL",
            "source_account": "personal@example.com",
            "discovered": 2,
            "created": 2,
            "existing": 0,
            "needs_review": 0,
            "skipped": 0,
            "cursor_value": "100",
        }

    monkeypatch.setattr(gmail_integration, "sync_mailbox", fake_sync)

    response = client.post("/api/integrations/gmail/sync")

    assert response.status_code == 200
    assert response.json()["created"] == 2
    assert calls["owner_sub"] == principal["sub"]


@pytest.mark.parametrize(
    ("exception_name", "expected_status"),
    [
        ("GmailDisabled", 503),
        ("GmailNotConfigured", 503),
        ("GmailRemoteError", 502),
    ],
)
def test_gmail_sync_translates_operational_failures(
    api,
    monkeypatch,
    exception_name,
    expected_status,
):
    client, _ = api
    exception_type = getattr(gmail_integration, exception_name)

    def fake_sync(*args, **kwargs):
        raise exception_type(exception_name)

    monkeypatch.setattr(gmail_integration, "sync_mailbox", fake_sync)

    response = client.post("/api/integrations/gmail/sync")

    assert response.status_code == expected_status
    assert "detail" in response.json()


def test_gmail_reset_to_current_uses_authenticated_owner(api, monkeypatch):
    client, principal = api
    calls = {}

    def fake_reset(db, *, owner_sub):
        calls.update(db=db, owner_sub=owner_sub)
        return {
            "source_account": "recruiting@example.com",
            "cursor_value": "999",
            "archived": 7,
            "archived_by_status": {"WAITING_DOWNLOAD": 6, "NEEDS_HUMAN": 1},
            "mode": "INCREMENTAL_FROM_NOW",
        }

    monkeypatch.setattr(gmail_integration, "reset_mailbox_to_current", fake_reset)

    response = client.post("/api/integrations/gmail/reset-to-current")

    assert response.status_code == 200
    assert response.json()["archived"] == 7
    assert calls["owner_sub"] == principal["sub"]


def test_reactivate_one_archived_uses_authenticated_owner(api, monkeypatch):
    client, principal = api
    calls = {}

    def fake_reactivate(db, *, owner_sub):
        calls.update(db=db, owner_sub=owner_sub)
        return {
            "reactivated": True,
            "task_id": "task-1",
            "status": "WAITING_DOWNLOAD",
            "candidate_name": "Ana Perez",
            "job_title": "Country Manager Chile",
        }

    monkeypatch.setattr(
        indeed_email_agent_service,
        "reactivate_one_archived_task",
        fake_reactivate,
    )

    response = client.post("/api/integrations/gmail/reactivate-one-archived")

    assert response.status_code == 200
    assert response.json()["reactivated"] is True
    assert response.json()["task_id"] == "task-1"
    assert calls["owner_sub"] == principal["sub"]


def test_retry_active_archived_test_uses_authenticated_owner(api, monkeypatch):
    client, principal = api
    calls = {}

    def fake_retry(db, *, owner_sub):
        calls.update(db=db, owner_sub=owner_sub)
        return {
            "retried": True,
            "task_id": "task-1",
            "status": "WAITING_DOWNLOAD",
            "candidate_name": "Ana Perez",
            "job_title": "Country Manager Chile",
        }

    monkeypatch.setattr(
        indeed_email_agent_service,
        "retry_active_needs_human_task",
        fake_retry,
    )

    response = client.post("/api/integrations/gmail/retry-active-archived-test")

    assert response.status_code == 200
    assert response.json()["retried"] is True
    assert calls["owner_sub"] == principal["sub"]


def test_active_archived_test_uses_authenticated_owner(api, monkeypatch):
    client, principal = api
    calls = {}

    def fake_get_active(db, *, owner_sub):
        calls.update(db=db, owner_sub=owner_sub)
        return {
            "task_id": "task-1",
            "status": "NEEDS_HUMAN",
            "candidate_name": "CESAR ARCILA",
            "job_title": "Líder de Contact Center Comercial",
            "last_error_code": "INDEED_UI_REQUIRES_REVIEW",
        }

    monkeypatch.setattr(
        indeed_email_agent_service,
        "get_active_smoke_task",
        fake_get_active,
    )

    response = client.get("/api/integrations/gmail/active-archived-test")

    assert response.status_code == 200
    assert response.json()["status"] == "NEEDS_HUMAN"
    assert calls["owner_sub"] == principal["sub"]


def test_gmail_status_passes_authenticated_owner(api, monkeypatch):
    client, principal = api
    calls = {}

    def fake_status(*, owner_sub):
        calls["owner_sub"] = owner_sub
        return {
            "enabled": True,
            "configured": True,
            "connected": True,
            "connected_email": None,
            "manageable": False,
        }

    monkeypatch.setattr(gmail_integration, "integration_status", fake_status)

    response = client.get("/api/integrations/gmail/status")

    assert response.status_code == 200
    assert calls["owner_sub"] == principal["sub"]


def test_gmail_disconnect_passes_authenticated_owner(api, monkeypatch):
    client, principal = api
    calls = {}

    def fake_disconnect(*, owner_sub):
        calls["owner_sub"] = owner_sub
        return {"connected": False}

    monkeypatch.setattr(gmail_integration, "disconnect_oauth", fake_disconnect)

    response = client.delete("/api/integrations/gmail")

    assert response.status_code == 200
    assert calls["owner_sub"] == principal["sub"]
