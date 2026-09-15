"""Focused contracts for the Evaluations HTTP application boundary."""

from types import SimpleNamespace

import pytest

from app.domains.evaluations import service


def test_owner_scoped_entrypoint_resolves_objects_then_delegates(monkeypatch):
    candidate = SimpleNamespace(id="candidate-1")
    job = SimpleNamespace(id="job-1")
    db = object()
    events = []
    expected = (SimpleNamespace(id="evaluation-1"), True, None)

    def require_candidate(db_arg, candidate_id, owner_sub):
        events.append(("candidate", db_arg, candidate_id, owner_sub))
        return candidate

    def get_job(db_arg, job_id, owner_sub=None):
        events.append(("job", db_arg, job_id, owner_sub))
        return job

    def evaluate(db_arg, *, candidate, job):
        events.append(("evaluate", db_arg, candidate.id, job.id))
        return expected

    monkeypatch.setattr(service.candidates_service, "require_candidate", require_candidate)
    monkeypatch.setattr(service.jobs_repository, "get_job", get_job)
    monkeypatch.setattr(service, "evaluate_candidate_for_job", evaluate)

    result = service.evaluate_candidate_for_owner(
        db,
        candidate_id="candidate-1",
        job_id="job-1",
        owner_sub="owner-1",
    )

    assert result is expected
    assert events == [
        ("candidate", db, "candidate-1", "owner-1"),
        ("job", db, "job-1", "owner-1"),
        ("evaluate", db, "candidate-1", "job-1"),
    ]


def test_owner_scoped_entrypoint_propagates_candidate_not_found(monkeypatch):
    def missing_candidate(*args, **kwargs):
        raise service.CandidateNotFound("candidate-1")

    monkeypatch.setattr(
        service.candidates_service,
        "require_candidate",
        missing_candidate,
    )

    with pytest.raises(service.CandidateNotFound):
        service.evaluate_candidate_for_owner(
            object(),
            candidate_id="candidate-1",
            job_id="job-1",
            owner_sub="owner-1",
        )


def test_owner_scoped_entrypoint_raises_job_not_found(monkeypatch):
    candidate = SimpleNamespace(id="candidate-1")
    monkeypatch.setattr(
        service.candidates_service,
        "require_candidate",
        lambda *args, **kwargs: candidate,
    )
    monkeypatch.setattr(
        service.jobs_repository,
        "get_job",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(service.JobNotFound):
        service.evaluate_candidate_for_owner(
            object(),
            candidate_id="candidate-1",
            job_id="missing-job",
            owner_sub="owner-1",
        )
