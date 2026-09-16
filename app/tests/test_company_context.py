"""Contracts for tenant-scoped versioned company context."""

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.jobs.company_context_model import CompanyContext
from app.domains.jobs.company_context import (
    ASIATI_CONTEXT_V1,
    CompanyContextPayload,
    ensure_asiati_context_v1,
    get_active_company_context,
    validated_context_payload,
)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_active_company_context_is_tenant_scoped():
    engine, db = _db()
    try:
        own = CompanyContext(
            owner_sub="owner-1",
            organization_name="ASIATI Corp",
            version=1,
            status="ACTIVE",
            context=ASIATI_CONTEXT_V1,
        )
        other = CompanyContext(
            owner_sub="owner-2",
            organization_name="Other",
            version=1,
            status="ACTIVE",
            context=ASIATI_CONTEXT_V1,
        )
        db.add_all([own, other])
        db.commit()

        result = get_active_company_context(db, owner_sub="owner-1")
        assert result is not None
        assert result.id == own.id
        assert result.owner_sub == "owner-1"
    finally:
        db.close()
        engine.dispose()


def test_company_context_version_is_unique_per_owner():
    engine, db = _db()
    try:
        db.add_all(
            [
                CompanyContext(
                    owner_sub="owner-1",
                    organization_name="ASIATI Corp",
                    version=1,
                    status="ACTIVE",
                    context=ASIATI_CONTEXT_V1,
                ),
                CompanyContext(
                    owner_sub="owner-1",
                    organization_name="ASIATI Corp",
                    version=1,
                    status="ARCHIVED",
                    context=ASIATI_CONTEXT_V1,
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def test_asiati_context_v1_is_strict_and_contains_no_candidate_data():
    payload = CompanyContextPayload.model_validate(ASIATI_CONTEXT_V1)
    dumped = payload.model_dump()
    text = str(dumped).casefold()

    assert payload.business_summary
    assert payload.operating_context
    assert payload.business_capabilities
    assert payload.culture_principles
    assert payload.talent_principles
    assert payload.recruiter_guidance
    for forbidden in ("candidate_id", "resume", "cv", "evaluation", "email"):
        assert forbidden not in text


def test_malformed_context_is_rejected_at_validation_boundary():
    with pytest.raises(ValidationError):
        CompanyContextPayload.model_validate(
            {
                "business_summary": "ASIATI",
                "operating_context": "not-a-list",
                "business_capabilities": [],
                "culture_principles": [],
                "talent_principles": [],
                "recruiter_guidance": [],
                "unexpected": True,
            }
        )


def test_ensure_asiati_context_v1_is_idempotent_for_authenticated_owner():
    engine, db = _db()
    try:
        first = ensure_asiati_context_v1(db, owner_sub="owner-1")
        second = ensure_asiati_context_v1(db, owner_sub="owner-1")

        assert first.id == second.id
        assert first.owner_sub == "owner-1"
        assert first.organization_name == "ASIATI Corp"
        assert first.version == 1
        assert first.status == "ACTIVE"
        assert db.query(CompanyContext).filter(CompanyContext.owner_sub == "owner-1").count() == 1
        assert validated_context_payload(first).business_summary
    finally:
        db.close()
        engine.dispose()
