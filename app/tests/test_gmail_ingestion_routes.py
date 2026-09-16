"""HTTP contracts for configurable Gmail candidate ingestion."""

import pytest
from fastapi.testclient import TestClient

from app.deps import get_current_user, get_db
from app.domains.candidate_ingestion import gmail_integration
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
        lambda: {
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
