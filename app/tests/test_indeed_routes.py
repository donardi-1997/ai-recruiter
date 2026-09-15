"""HTTP contracts for Indeed candidate and disposition sync routes."""

import pytest
from fastapi.testclient import TestClient

from app.deps import get_current_user, get_db
from app.domains.candidate_imports.exceptions import IdentityConflict
from app.domains.indeed import service as indeed_service
from app.domains.indeed.exceptions import (
    IndeedDisabled,
    IndeedLinkNotFound,
    IndeedNotConfigured,
    IndeedRemoteError,
    IndeedValidationError,
)
from app.main import app


@pytest.fixture()
def api():
    principal = {"sub": "owner-a", "email": "recruiter@asiati.com"}

    def override_db():
        yield object()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: dict(principal)
    with TestClient(app) as client:
        yield client, principal
    app.dependency_overrides.clear()


def test_candidate_sync_route_passes_owner_and_limit(api, monkeypatch):
    client, principal = api
    calls = {}

    def fake_sync(db, *, owner_sub, limit=25, client=None, settings=None):
        calls.update(db=db, owner_sub=owner_sub, limit=limit)
        return {
            "fetched": 2,
            "created": 1,
            "reused": 1,
            "skipped": 0,
            "next_token_present": True,
            "last_sync_at": "2026-09-15T22:00:00+00:00",
        }

    monkeypatch.setattr(indeed_service, "sync_candidates", fake_sync)

    response = client.post("/api/integrations/indeed/candidates/sync?limit=7")

    assert response.status_code == 200
    assert response.json()["created"] == 1
    assert calls["owner_sub"] == principal["sub"]
    assert calls["limit"] == 7


def test_disposition_sync_route_passes_owner_and_limit(api, monkeypatch):
    client, principal = api
    calls = {}

    def fake_sync(db, *, owner_sub, limit=25, client=None, settings=None):
        calls.update(db=db, owner_sub=owner_sub, limit=limit)
        return {"selected": 2, "sent": 2, "failed": 0}

    monkeypatch.setattr(indeed_service, "sync_dispositions", fake_sync)

    response = client.post("/api/integrations/indeed/dispositions/sync?limit=9")

    assert response.status_code == 200
    assert response.json() == {"selected": 2, "sent": 2, "failed": 0}
    assert calls["owner_sub"] == principal["sub"]
    assert calls["limit"] == 9


@pytest.mark.parametrize(
    ("exception", "expected_status"),
    [
        (IndeedLinkNotFound("candidate link missing"), 404),
        (IndeedValidationError("invalid asset"), 422),
        (IndeedDisabled("Indeed disabled"), 503),
        (IndeedNotConfigured("Indeed not configured"), 503),
        (IndeedRemoteError("Indeed unavailable"), 502),
        (IdentityConflict("conflicting identities"), 409),
    ],
)
def test_candidate_sync_route_translates_domain_failures(api, monkeypatch, exception, expected_status):
    client, _ = api

    def fake_sync(*args, **kwargs):
        raise exception

    monkeypatch.setattr(indeed_service, "sync_candidates", fake_sync)

    response = client.post("/api/integrations/indeed/candidates/sync")

    assert response.status_code == expected_status
    assert "detail" in response.json()


def test_manual_sync_routes_reject_out_of_range_batch_limits(api):
    client, _ = api

    candidate_response = client.post("/api/integrations/indeed/candidates/sync?limit=101")
    disposition_response = client.post("/api/integrations/indeed/dispositions/sync?limit=26")

    assert candidate_response.status_code == 422
    assert disposition_response.status_code == 422
