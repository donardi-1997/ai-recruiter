"""Contracts for safe identity backfill of candidates created before import V1."""

import importlib
import os
import tempfile

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Candidate, CandidateIdentity


@pytest.fixture()
def db_session():
    fd, path = tempfile.mkstemp(suffix=".db")
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
        os.close(fd)
        os.unlink(path)


def _backfill_module():
    return importlib.import_module("app.scripts.backfill_candidate_identities")


def test_backfill_skips_ambiguous_email_collision(db_session, monkeypatch):
    backfill = _backfill_module()
    db_session.add_all([
        Candidate(name="Ana 1", email="ANA@example.com", owner_sub="owner-a"),
        Candidate(name="Ana 2", email="ana@example.com", owner_sub="owner-a"),
    ])
    db_session.commit()
    monkeypatch.setattr(backfill, "read_existing_canonical_document", lambda candidate_id: None)

    result = backfill.backfill_candidate_identities(db_session)

    assert result["email_conflicts"] == 1
    assert (
        db_session.query(CandidateIdentity)
        .filter_by(owner_sub="owner-a", kind="EMAIL", value="ana@example.com")
        .count()
        == 0
    )


def test_backfill_is_idempotent(db_session, monkeypatch):
    backfill = _backfill_module()
    candidate = Candidate(
        name="Beto",
        email=" BETO@example.com ",
        owner_sub="owner-a",
    )
    db_session.add(candidate)
    db_session.commit()
    monkeypatch.setattr(
        backfill,
        "read_existing_canonical_document",
        lambda candidate_id: b"same-cv",
    )

    backfill.backfill_candidate_identities(db_session)
    backfill.backfill_candidate_identities(db_session)

    identities = (
        db_session.query(CandidateIdentity)
        .filter_by(candidate_id=candidate.id)
        .order_by(CandidateIdentity.kind)
        .all()
    )
    assert [(identity.kind, identity.value) for identity in identities] == [
        ("DOCUMENT_SHA256", backfill.document_sha256(b"same-cv")),
        ("EMAIL", "beto@example.com"),
    ]


def test_backfill_skips_ownerless_candidate(db_session, monkeypatch):
    backfill = _backfill_module()
    candidate = Candidate(name="Legacy", email="legacy@example.com", owner_sub=None)
    db_session.add(candidate)
    db_session.commit()
    monkeypatch.setattr(backfill, "read_existing_canonical_document", lambda candidate_id: b"cv")

    result = backfill.backfill_candidate_identities(db_session)

    assert result["skipped_ownerless"] == 1
    assert db_session.query(CandidateIdentity).filter_by(candidate_id=candidate.id).count() == 0


def test_backfill_same_email_isolated_by_owner(db_session, monkeypatch):
    backfill = _backfill_module()
    first = Candidate(name="Ana A", email="ana@example.com", owner_sub="owner-a")
    second = Candidate(name="Ana B", email="ANA@example.com", owner_sub="owner-b")
    db_session.add_all([first, second])
    db_session.commit()
    monkeypatch.setattr(backfill, "read_existing_canonical_document", lambda candidate_id: None)

    result = backfill.backfill_candidate_identities(db_session)

    assert result["email_conflicts"] == 0
    assert (
        db_session.query(CandidateIdentity)
        .filter_by(kind="EMAIL", value="ana@example.com")
        .count()
        == 2
    )
