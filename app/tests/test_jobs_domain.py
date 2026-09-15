"""Focused tests for the Jobs application boundary."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.domains.jobs import presenter, service


def _job(**overrides):
    values = {
        "id": "job-1",
        "title": "Backend Developer",
        "description": "Python APIs",
        "created_at": datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_require_job_scopes_lookup_to_owner(monkeypatch):
    expected = _job()
    calls = []

    def fake_get_job(db, job_id, owner_sub=None):
        calls.append((db, job_id, owner_sub))
        return expected

    monkeypatch.setattr(service.repository, "get_job", fake_get_job)
    db = object()

    result = service.require_job(db, "job-1", "owner-1")

    assert result is expected
    assert calls == [(db, "job-1", "owner-1")]


def test_require_job_raises_domain_error_when_invisible(monkeypatch):
    monkeypatch.setattr(service.repository, "get_job", lambda *args, **kwargs: None)

    with pytest.raises(service.JobNotFound):
        service.require_job(object(), "job-1", "owner-1")


def test_list_jobs_returns_candidate_counts_scoped_to_owner(monkeypatch):
    first = _job(id="job-1")
    second = _job(id="job-2")
    count_calls = []

    monkeypatch.setattr(
        service.repository,
        "list_jobs",
        lambda db, owner_sub=None: [first, second],
    )

    def fake_count(db, job_id, owner_sub=None):
        count_calls.append((job_id, owner_sub))
        return {"job-1": 3, "job-2": 1}[job_id]

    monkeypatch.setattr(service.repository, "count_candidates_for_job", fake_count)

    result = service.list_jobs(object(), "owner-1")

    assert result == [(first, 3), (second, 1)]
    assert count_calls == [("job-1", "owner-1"), ("job-2", "owner-1")]


def test_create_job_delegates_owner_scoped_fields(monkeypatch):
    expected = _job()
    calls = []

    def fake_create(db, *, title, description, owner_sub):
        calls.append((db, title, description, owner_sub))
        return expected

    monkeypatch.setattr(service.repository, "create_job", fake_create)
    db = object()

    result = service.create_job(
        db,
        title="Backend Developer",
        description="Python APIs",
        owner_sub="owner-1",
    )

    assert result is expected
    assert calls == [(db, "Backend Developer", "Python APIs", "owner-1")]


def test_update_job_requires_owner_then_delegates(monkeypatch):
    existing = _job()
    updated = _job(title="Senior Backend Developer")
    events = []

    def fake_get(db, job_id, owner_sub=None):
        events.append(("get", job_id, owner_sub))
        return existing

    def fake_update(db, job, *, title=None, description=None):
        events.append(("update", job, title, description))
        return updated

    monkeypatch.setattr(service.repository, "get_job", fake_get)
    monkeypatch.setattr(service.repository, "update_job", fake_update)

    result = service.update_job(
        object(),
        job_id="job-1",
        title="Senior Backend Developer",
        description=None,
        owner_sub="owner-1",
    )

    assert result is updated
    assert events[0] == ("get", "job-1", "owner-1")
    assert events[1][0] == "update"
    assert events[1][1] is existing
    assert events[1][2:] == ("Senior Backend Developer", None)


def test_delete_job_requires_owner_and_returns_deleted_count(monkeypatch):
    existing = _job()
    events = []

    def fake_get(db, job_id, owner_sub=None):
        events.append(("get", job_id, owner_sub))
        return existing

    def fake_delete(db, job_id, *, owner_sub=None, delete_candidates=False):
        events.append(("delete", job_id, owner_sub, delete_candidates))
        return True, 4

    monkeypatch.setattr(service.repository, "get_job", fake_get)
    monkeypatch.setattr(service.repository, "delete_job", fake_delete)

    deleted_count = service.delete_job(
        object(),
        job_id="job-1",
        owner_sub="owner-1",
        delete_candidates=True,
    )

    assert deleted_count == 4
    assert events == [
        ("get", "job-1", "owner-1"),
        ("delete", "job-1", "owner-1", True),
    ]


def test_job_payload_preserves_list_shape_with_candidate_count():
    payload = presenter.job_payload(_job(), candidate_count=3)

    assert payload == {
        "job_id": "job-1",
        "id": "job-1",
        "title": "Backend Developer",
        "description": "Python APIs",
        "created_at": "2026-09-11T12:00:00+00:00",
        "candidate_count": 3,
    }


def test_job_payload_omits_candidate_count_for_create_and_update():
    payload = presenter.job_payload(_job())

    assert payload == {
        "job_id": "job-1",
        "id": "job-1",
        "title": "Backend Developer",
        "description": "Python APIs",
        "created_at": "2026-09-11T12:00:00+00:00",
    }


def test_delete_job_payload_preserves_exact_public_contract():
    assert presenter.delete_job_payload("job-1", False, 0) == {
        "detail": "Vacante eliminada.",
        "job_id": "job-1",
        "delete_candidates": False,
        "deleted_candidates": 0,
    }
    assert presenter.delete_job_payload("job-1", True, 4) == {
        "detail": "Vacante y candidatos eliminados.",
        "job_id": "job-1",
        "delete_candidates": True,
        "deleted_candidates": 4,
    }
