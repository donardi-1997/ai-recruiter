"""Contracts for source-account isolation and durable ingestion cursors."""

import importlib

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base


def _models():
    return importlib.import_module("app.domains.candidate_ingestion.models")


def test_same_external_message_id_is_allowed_for_different_source_accounts():
    models = _models()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add_all(
                [
                    models.CandidateIngestionEvent(
                        owner_sub="owner-1",
                        source="EMAIL",
                        provider="INDEED",
                        source_account="personal@example.com",
                        external_id="gmail-1",
                        status="RECEIVED",
                    ),
                    models.CandidateIngestionEvent(
                        owner_sub="owner-1",
                        source="EMAIL",
                        provider="INDEED",
                        source_account="corporate@example.com",
                        external_id="gmail-1",
                        status="RECEIVED",
                    ),
                ]
            )
            db.commit()
            assert db.query(models.CandidateIngestionEvent).count() == 2
    finally:
        engine.dispose()


def test_cursor_is_unique_per_owner_source_provider_and_source_account():
    models = _models()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            personal = models.CandidateIngestionCursor(
                owner_sub="owner-1",
                source="EMAIL",
                provider="INDEED",
                source_account="personal@example.com",
                cursor_value="100",
            )
            corporate = models.CandidateIngestionCursor(
                owner_sub="owner-1",
                source="EMAIL",
                provider="INDEED",
                source_account="corporate@example.com",
                cursor_value="200",
            )
            db.add_all([personal, corporate])
            db.commit()

            assert personal.cursor_value == "100"
            assert corporate.cursor_value == "200"
            assert personal.id != corporate.id
    finally:
        engine.dispose()
