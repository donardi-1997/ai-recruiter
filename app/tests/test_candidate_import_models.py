"""Persistence contracts for durable candidate import batches."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app import models


def test_candidate_import_models_exist():
    assert hasattr(models, "ImportBatch")
    assert hasattr(models, "ImportItem")
    assert hasattr(models, "CandidateIdentity")


def test_candidate_import_tables_exist():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    assert {"import_batches", "import_items", "candidate_identities"} <= set(
        inspect(engine).get_table_names()
    )


def test_candidate_identity_is_unique_per_owner_kind_value():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    candidate_identity = getattr(models, "CandidateIdentity")
    with Session(engine) as db:
        candidate = models.Candidate(name="Ana", owner_sub="owner-a")
        db.add(candidate)
        db.commit()

        db.add(
            candidate_identity(
                owner_sub="owner-a",
                candidate_id=candidate.id,
                kind="EMAIL",
                value="ana@example.com",
            )
        )
        db.commit()

        db.add(
            candidate_identity(
                owner_sub="owner-a",
                candidate_id=candidate.id,
                kind="EMAIL",
                value="ana@example.com",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_same_identity_value_is_allowed_for_different_owners():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    candidate_identity = getattr(models, "CandidateIdentity")
    with Session(engine) as db:
        first = models.Candidate(name="Ana A", owner_sub="owner-a")
        second = models.Candidate(name="Ana B", owner_sub="owner-b")
        db.add_all([first, second])
        db.commit()

        db.add_all(
            [
                candidate_identity(
                    owner_sub="owner-a",
                    candidate_id=first.id,
                    kind="EMAIL",
                    value="ana@example.com",
                ),
                candidate_identity(
                    owner_sub="owner-b",
                    candidate_id=second.id,
                    kind="EMAIL",
                    value="ana@example.com",
                ),
            ]
        )
        db.commit()

        assert db.query(candidate_identity).count() == 2


def test_migration_003_is_additive_and_points_to_002():
    migration = Path("app/migrations/versions/003_candidate_imports.py")

    assert migration.exists()
    text = migration.read_text(encoding="utf-8")
    assert 'revision = "003"' in text
    assert 'down_revision = "002"' in text
    assert 'op.create_table(\n        "import_batches"' in text
    assert 'op.create_table(\n        "import_items"' in text
    assert 'op.create_table(\n        "candidate_identities"' in text
