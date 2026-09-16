"""Contracts for provider-neutral candidate identity resolution."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.candidates import identity
from app.models import Candidate, CandidateIdentity


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def _parsed(*, sha="a" * 64, email="Ana@Example.com", phone="+57 300 111 2233"):
    return SimpleNamespace(
        sha256=sha,
        email=email,
        phone=phone,
        display_name="Ana Perez",
        filename="ana.pdf",
    )


def test_resolve_or_create_candidate_creates_owner_scoped_strong_identities():
    engine, db = _db()
    try:
        candidate, outcome = identity.resolve_or_create_candidate(
            db,
            owner_sub="owner-1",
            parsed_document=_parsed(),
        )

        assert outcome == "CREATED"
        assert candidate.owner_sub == "owner-1"
        assert candidate.email == "ana@example.com"
        identities = db.query(CandidateIdentity).filter_by(candidate_id=candidate.id).all()
        assert {(item.kind, item.value) for item in identities} == {
            ("DOCUMENT_SHA256", "a" * 64),
            ("EMAIL", "ana@example.com"),
            ("PHONE", "+573001112233"),
        }
    finally:
        db.close()
        engine.dispose()


def test_same_document_reuses_candidate_without_job_dependency():
    engine, db = _db()
    try:
        first, _ = identity.resolve_or_create_candidate(
            db, owner_sub="owner-1", parsed_document=_parsed()
        )
        second, outcome = identity.resolve_or_create_candidate(
            db,
            owner_sub="owner-1",
            parsed_document=_parsed(email=None, phone=None),
        )

        assert outcome == "REUSED"
        assert second.id == first.id
        assert db.query(Candidate).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_conflicting_strong_identities_never_merge_people():
    engine, db = _db()
    try:
        first, _ = identity.resolve_or_create_candidate(
            db,
            owner_sub="owner-1",
            parsed_document=_parsed(sha="a" * 64, email="a@example.com", phone=None),
        )
        second, _ = identity.resolve_or_create_candidate(
            db,
            owner_sub="owner-1",
            parsed_document=_parsed(sha="b" * 64, email="b@example.com", phone=None),
        )
        assert first.id != second.id

        with pytest.raises(identity.CandidateIdentityConflict):
            identity.resolve_or_create_candidate(
                db,
                owner_sub="owner-1",
                parsed_document=_parsed(
                    sha="a" * 64,
                    email="b@example.com",
                    phone=None,
                ),
            )
    finally:
        db.close()
        engine.dispose()


def test_identity_resolution_is_tenant_scoped():
    engine, db = _db()
    try:
        first, _ = identity.resolve_or_create_candidate(
            db, owner_sub="owner-1", parsed_document=_parsed()
        )
        second, _ = identity.resolve_or_create_candidate(
            db, owner_sub="owner-2", parsed_document=_parsed()
        )
        assert first.id != second.id
    finally:
        db.close()
        engine.dispose()
