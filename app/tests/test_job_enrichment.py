"""Contracts for optional AI enrichment of an unsaved vacancy draft."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.jobs.company_context import ASIATI_CONTEXT_V1
from app.domains.jobs.company_context_model import CompanyContext
from app.domains.jobs.enrichment import SYSTEM_PROMPT, JobEnrichmentError, enrich_job_draft
from app.domains.jobs.schemas import JobEnrichmentRequest
from app.models import Job


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def _proposal():
    return {
        "improved_description": "Diseña y opera plataformas cloud medibles, seguras y escalables.",
        "required_technologies": ["AWS"],
        "preferred_technologies": ["Terraform"],
        "required_certifications": [],
        "preferred_certifications": ["AWS Solutions Architect"],
        "minimum_years_experience": 3,
        "specific_experience": ["Infraestructura como código"],
        "responsibilities": ["Operar infraestructura cloud"],
        "domain_knowledge": ["Cloud operations"],
        "education": [],
        "languages": ["Inglés deseable para colaboración internacional"],
        "technical_competencies": ["Observabilidad"],
        "assumptions_to_validate": ["Confirmar si EKS forma parte del stack"],
    }


def test_enrichment_uses_active_tenant_context_and_returns_version():
    engine, db = _db()
    try:
        own_context = dict(ASIATI_CONTEXT_V1)
        own_context["business_summary"] = "Contexto exclusivo owner-1"
        other_context = dict(ASIATI_CONTEXT_V1)
        other_context["business_summary"] = "SECRET OTHER TENANT"
        db.add_all(
            [
                CompanyContext(
                    owner_sub="owner-1",
                    organization_name="ASIATI Corp",
                    version=3,
                    status="ACTIVE",
                    context=own_context,
                ),
                CompanyContext(
                    owner_sub="owner-2",
                    organization_name="Other",
                    version=9,
                    status="ACTIVE",
                    context=other_context,
                ),
            ]
        )
        db.commit()
        prompts = []

        def fake_model(prompt):
            prompts.append(prompt)
            return _proposal()

        proposal, context_version = enrich_job_draft(
            db,
            owner_sub="owner-1",
            request=JobEnrichmentRequest(
                title="Cloud Engineer",
                description="Necesitamos apoyo con AWS.",
                country_code="CO",
                city="Bogotá",
                employment_type="FULL_TIME",
            ),
            model_client=fake_model,
        )

        assert context_version == 3
        assert proposal.required_technologies == ["AWS"]
        assert len(prompts) == 1
        assert "COMPANY_CONTEXT" in prompts[0]
        assert "JOB_DRAFT" in prompts[0]
        assert "OUTPUT_CONTRACT" in prompts[0]
        assert "OUTPUT_LANGUAGE" in prompts[0]
        assert "es-CO" in prompts[0]
        assert "español" in prompts[0]
        assert "Contexto exclusivo owner-1" in prompts[0]
        assert "SECRET OTHER TENANT" not in prompts[0]
    finally:
        db.close()
        engine.dispose()


def test_enrichment_auto_provisions_asiati_v1_for_authenticated_tenant():
    engine, db = _db()
    try:
        proposal, context_version = enrich_job_draft(
            db,
            owner_sub="owner-new",
            request=JobEnrichmentRequest(title="Country Manager"),
            model_client=lambda _prompt: _proposal(),
        )

        assert proposal.improved_description
        assert context_version == 1
        row = (
            db.query(CompanyContext)
            .filter(CompanyContext.owner_sub == "owner-new")
            .one()
        )
        assert row.organization_name == "ASIATI Corp"
    finally:
        db.close()
        engine.dispose()


def test_enrichment_does_not_create_or_mutate_job():
    engine, db = _db()
    try:
        existing = Job(
            title="Existing",
            description="Original description",
            owner_sub="owner-1",
            evaluation_version=4,
        )
        db.add(existing)
        db.commit()
        before_count = db.query(Job).count()

        enrich_job_draft(
            db,
            owner_sub="owner-1",
            request=JobEnrichmentRequest(
                title="New Draft",
                description="Draft text",
            ),
            model_client=lambda _prompt: _proposal(),
        )

        db.refresh(existing)
        assert db.query(Job).count() == before_count
        assert existing.description == "Original description"
        assert existing.evaluation_version == 4
    finally:
        db.close()
        engine.dispose()


def test_enrichment_rejects_malformed_model_payload_without_job_write():
    engine, db = _db()
    try:
        with pytest.raises(JobEnrichmentError):
            enrich_job_draft(
                db,
                owner_sub="owner-1",
                request=JobEnrichmentRequest(title="Cloud Engineer"),
                model_client=lambda _prompt: {"improved_description": "missing fields", "unexpected": True},
            )
        assert db.query(Job).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_enrichment_prompt_contains_no_candidate_data():
    engine, db = _db()
    try:
        prompts = []
        request = JobEnrichmentRequest(
            title="Operations Manager",
            description="Coordinate cross-border operations.",
        )
        enrich_job_draft(
            db,
            owner_sub="owner-1",
            request=request,
            model_client=lambda prompt: prompts.append(prompt) or _proposal(),
        )
        prompt = prompts[0].casefold()
        for forbidden in ("candidate_id", "resume_url", "candidate_email"):
            assert forbidden not in prompt
        json.dumps(request.model_dump(), default=str)
    finally:
        db.close()
        engine.dispose()



def test_enrichment_system_prompt_requires_spanish_values_and_preserves_official_names():
    prompt = SYSTEM_PROMPT
    assert "EN ESPAÑOL" in prompt
    assert "claves JSON" in prompt
    assert "AWS" in prompt
    assert "Terraform" in prompt
