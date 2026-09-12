"""Focused contracts for the Candidates application boundary."""

from types import SimpleNamespace

import pytest

from app.domains.candidates import presenter, service
from app.domains.candidates.exceptions import CandidateNotFound, JobNotFound


PUBLIC_FAILURE = "No fue posible completar la evaluación. Intenta nuevamente."


def _candidate(**overrides):
    values = {
        "id": "candidate-1",
        "name": "Ana Test",
        "email": "ana@example.com",
        "created_at": None,
        "metadata_": {"filename": "ana.pdf"},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _evaluation(**overrides):
    values = {
        "id": "evaluation-1",
        "candidate_id": "candidate-1",
        "job_id": "job-1",
        "status": "COMPLETED",
        "match_score": 82,
        "recommendation": "GOOD_MATCH",
        "summary": "Resumen suficientemente detallado.",
        "strengths": ["Python"],
        "gaps": ["Kubernetes"],
        "requirements": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_candidate_to_dict_preserves_public_shape():
    candidate = _candidate()

    data = presenter.candidate_to_dict(candidate)

    assert data == {
        "candidate_id": "candidate-1",
        "id": "candidate-1",
        "name": "Ana Test",
        "email": "ana@example.com",
        "created_at": None,
        "metadata": {"filename": "ana.pdf"},
        "filename": "ana.pdf",
    }


def test_failed_evaluation_is_sanitized():
    evaluation = _evaluation(
        status="FAILED",
        match_score=91,
        recommendation="STRONG_MATCH",
        summary="AccessDeniedException arn:aws:secret",
        strengths=["secret"],
        gaps=["secret"],
        requirements=[{"requirement": "secret"}],
    )

    data = presenter.evaluation_to_dict(evaluation)

    assert data["match_score"] is None
    assert data["recommendation"] == "EVALUATION_FAILED"
    assert data["summary"] == PUBLIC_FAILURE
    assert data["strengths"] == []
    assert data["gaps"] == []
    assert data["requirements"] == []
    assert data["error_message"] == PUBLIC_FAILURE


def test_explanation_without_evaluation_preserves_pending_contract():
    assert presenter.evaluation_explanation_to_dict(None) == {
        "status": "PENDING",
        "explanation": "Sin evaluacion.",
        "summary": None,
        "analysis": None,
    }


def test_requirements_fallback_preserves_strength_gap_mapping():
    evaluation = _evaluation(requirements=[])

    assert presenter.evaluation_requirements_to_dict(evaluation) == {
        "requirements": [
            {"requirement": "Python", "status": "MATCH", "evidence": None},
            {"requirement": "Kubernetes", "status": "MISSING", "evidence": None},
        ]
    }


def test_require_candidate_scopes_lookup_to_owner(monkeypatch):
    candidate = _candidate()
    calls = []

    def fake_get(db, candidate_id, owner_sub=None):
        calls.append((db, candidate_id, owner_sub))
        return candidate

    monkeypatch.setattr(service.candidates_repository, "get_candidate", fake_get)
    db = object()

    assert service.require_candidate(db, "candidate-1", "owner-1") is candidate
    assert calls == [(db, "candidate-1", "owner-1")]


def test_require_candidate_raises_domain_error_when_invisible(monkeypatch):
    monkeypatch.setattr(
        service.candidates_repository,
        "get_candidate",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(CandidateNotFound):
        service.require_candidate(object(), "missing", "owner-1")


def test_require_job_scopes_lookup_to_owner(monkeypatch):
    job = SimpleNamespace(id="job-1")
    calls = []

    def fake_get(db, job_id, owner_sub=None):
        calls.append((db, job_id, owner_sub))
        return job

    monkeypatch.setattr(service.jobs_repository, "get_job", fake_get)
    db = object()

    assert service.require_job(db, "job-1", "owner-1") is job
    assert calls == [(db, "job-1", "owner-1")]


def test_require_job_raises_domain_error_when_invisible(monkeypatch):
    monkeypatch.setattr(
        service.jobs_repository,
        "get_job",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(JobNotFound):
        service.require_job(object(), "missing", "owner-1")


def test_assign_candidates_validates_job_then_delegates(monkeypatch):
    events = []

    monkeypatch.setattr(
        service,
        "require_job",
        lambda db, job_id, owner_sub: events.append(("job", job_id, owner_sub)),
    )

    def fake_assign(db, job_id, candidate_ids, owner_sub=None):
        events.append(("assign", job_id, tuple(candidate_ids), owner_sub))
        return 2, 1

    monkeypatch.setattr(
        service.candidates_repository,
        "assign_candidates_to_job",
        fake_assign,
    )

    result = service.assign_candidates(
        object(),
        "job-1",
        ["c1", "c2", "missing"],
        "owner-1",
    )

    assert result == (2, 1)
    assert events == [
        ("job", "job-1", "owner-1"),
        ("assign", "job-1", ("c1", "c2", "missing"), "owner-1"),
    ]


def test_delete_candidate_validates_owner_before_delete(monkeypatch):
    events = []
    candidate = _candidate()

    monkeypatch.setattr(
        service,
        "require_candidate",
        lambda db, candidate_id, owner_sub: events.append(("require", candidate_id, owner_sub)) or candidate,
    )
    monkeypatch.setattr(
        service.candidates_repository,
        "delete_candidate",
        lambda db, candidate_id: events.append(("delete", candidate_id)) or True,
    )

    assert service.delete_candidate(object(), "candidate-1", "owner-1") is True
    assert events == [
        ("require", "candidate-1", "owner-1"),
        ("delete", "candidate-1"),
    ]


def test_create_and_index_candidate_preserves_create_before_index(monkeypatch):
    events = []
    candidate = _candidate(name="resume")

    def fake_create(db, *, name, email=None, metadata=None, owner_sub=None):
        events.append(("create", name, metadata, owner_sub))
        return candidate

    def fake_index(created_candidate, file_content, filename):
        events.append(("index", created_candidate, file_content, filename))
        return {"status": "COMPLETE", "ingestion_job_id": "job-123", "error": None}

    monkeypatch.setattr(service.candidates_repository, "create_candidate", fake_create)
    monkeypatch.setattr(service, "index_candidate_document", fake_index)

    created, indexing = service.create_and_index_candidate(
        object(),
        owner_sub="owner-1",
        original_filename="resume.pdf",
        file_content=b"pdf",
    )

    assert created is candidate
    assert indexing == {
        "status": "COMPLETE",
        "ingestion_job_id": "job-123",
        "error": None,
    }
    assert events == [
        ("create", "resume", {"filename": "resume.pdf"}, "owner-1"),
        ("index", candidate, b"pdf", "resume.pdf"),
    ]


def test_create_and_index_candidate_does_not_swallow_index_failure(monkeypatch):
    candidate = _candidate(name="resume")
    events = []

    monkeypatch.setattr(
        service.candidates_repository,
        "create_candidate",
        lambda *args, **kwargs: events.append("create") or candidate,
    )

    def fail_index(*args, **kwargs):
        events.append("index")
        raise RuntimeError("index failed")

    monkeypatch.setattr(service, "index_candidate_document", fail_index)

    with pytest.raises(RuntimeError, match="index failed"):
        service.create_and_index_candidate(
            object(),
            owner_sub="owner-1",
            original_filename="resume.pdf",
            file_content=b"pdf",
        )

    assert events == ["create", "index"]
