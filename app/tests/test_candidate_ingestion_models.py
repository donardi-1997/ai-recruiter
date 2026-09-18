"""Persistence contracts for provider-neutral candidate ingestion."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as _core_models  # noqa: F401 - registers FK target tables
from app.db import Base


def _models_module():
    try:
        return importlib.import_module("app.domains.candidate_ingestion.models")
    except ModuleNotFoundError as exc:
        pytest.fail(f"candidate ingestion models are missing: {exc}")


def test_candidate_ingestion_tables_exist_and_support_unresolved_email_event():
    ingestion_models = _models_module()
    event_model = ingestion_models.CandidateIngestionEvent
    document_model = ingestion_models.CandidateIngestionDocument

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        assert {
            "candidate_ingestion_events",
            "candidate_ingestion_documents",
        } <= set(inspect(engine).get_table_names())

        with Session(engine) as db:
            event = event_model(
                owner_sub="owner-1",
                source="EMAIL",
                provider="INDEED",
                external_id="gmail-message-1",
                status="RECEIVED",
                raw_metadata={"subject": "New application"},
            )
            db.add(event)
            db.flush()
            document = document_model(
                ingestion_event_id=event.id,
                filename="ana.pdf",
                content_type="application/pdf",
                size_bytes=123,
                source_s3_key="email-ingestion/gmail-message-1/ana.pdf",
                status="STORED",
            )
            db.add(document)
            db.commit()
            db.refresh(event)
            db.refresh(document)

            assert event.job_id is None
            assert event.candidate_id is None
            assert event.attempt_count == 0
            assert event.queue_dispatched_at is None
            assert event.processing_token is None
            assert document.document_sha256 is None
            assert document.canonical_s3_key is None
    finally:
        engine.dispose()


def test_external_event_identity_is_unique_per_owner_source_provider():
    ingestion_models = _models_module()
    event_model = ingestion_models.CandidateIngestionEvent

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(
                event_model(
                    owner_sub="owner-1",
                    source="EMAIL",
                    provider="INDEED",
                    external_id="gmail-message-1",
                    status="RECEIVED",
                )
            )
            db.commit()

            db.add(
                event_model(
                    owner_sub="owner-1",
                    source="EMAIL",
                    provider="INDEED",
                    external_id="gmail-message-1",
                    status="RECEIVED",
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()
    finally:
        engine.dispose()


def test_same_external_id_is_allowed_for_different_owners():
    ingestion_models = _models_module()
    event_model = ingestion_models.CandidateIngestionEvent

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add_all(
                [
                    event_model(
                        owner_sub="owner-1",
                        source="EMAIL",
                        provider="INDEED",
                        external_id="gmail-message-1",
                        status="RECEIVED",
                    ),
                    event_model(
                        owner_sub="owner-2",
                        source="EMAIL",
                        provider="INDEED",
                        external_id="gmail-message-1",
                        status="RECEIVED",
                    ),
                ]
            )
            db.commit()
            assert db.query(event_model).count() == 2
    finally:
        engine.dispose()


def test_migration_007_is_additive_and_points_to_006():
    migration = Path("app/migrations/versions/007_candidate_ingestion_core.py")

    assert migration.exists()
    text = migration.read_text(encoding="utf-8")
    assert 'revision = "007"' in text
    assert 'down_revision = "006"' in text
    assert '"candidate_ingestion_events"' in text
    assert '"candidate_ingestion_documents"' in text


def test_migration_012_adds_indeed_job_discovery_key_after_011():
    migration = Path("app/migrations/versions/012_indeed_job_discovery_key.py")

    assert migration.exists()
    text = migration.read_text(encoding="utf-8")
    assert 'revision = "012"' in text
    assert 'down_revision = "011"' in text
    assert '"discovery_key"' in text
    assert '"uq_indeed_job_links_owner_discovery_key"' in text
