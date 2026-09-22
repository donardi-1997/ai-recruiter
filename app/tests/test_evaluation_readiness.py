from types import SimpleNamespace

import pytest

from app.domains.evaluations import service
from app.domains.jobs.profile import has_evaluation_criteria


def _job(**overrides):
    values = {
        "id": "job-1",
        "title": "Líder de Marketing y Crecimiento",
        "description": None,
        "evaluation_profile": {},
        "evaluation_version": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_title_only_auto_created_job_is_not_ready_for_evaluation():
    assert has_evaluation_criteria(_job()) is False


def test_description_or_structured_profile_makes_job_evaluable():
    assert has_evaluation_criteria(
        _job(description="Experiencia en growth marketing y adquisición digital.")
    ) is True
    assert has_evaluation_criteria(
        _job(
            evaluation_profile={
                "specific_experience": ["Growth marketing"],
                "minimum_years_experience": 2,
            }
        )
    ) is True


def test_evaluate_for_owner_rejects_title_only_job_before_llm(monkeypatch):
    candidate = SimpleNamespace(id="candidate-1")
    job = _job()
    monkeypatch.setattr(
        service.candidates_service,
        "require_candidate",
        lambda *args, **kwargs: candidate,
    )
    monkeypatch.setattr(
        service.jobs_repository,
        "get_job",
        lambda *args, **kwargs: job,
    )

    with pytest.raises(
        service.EvaluationCriteriaMissing,
        match="JOB_EVALUATION_CRITERIA_MISSING",
    ):
        service.evaluate_candidate_for_owner(
            object(),
            candidate_id="candidate-1",
            job_id="job-1",
            owner_sub="owner-1",
        )
