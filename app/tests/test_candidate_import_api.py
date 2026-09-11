"""HTTP contracts for durable candidate-import batches."""

from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.deps import get_current_user, get_db
from app.domains.candidate_imports import service
from app.main import app
from app.models import ImportBatch, ImportItem, Job


@pytest.fixture()
def db_session():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
        os.close(fd)
        os.unlink(db_path)


@pytest.fixture()
def api(db_session):
    principal = {"sub": "owner-a", "email": "a@example.com"}

    def override_db():
        Session = sessionmaker(bind=db_session.get_bind())
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: dict(principal)
    with TestClient(app) as client:
        yield client, principal
    app.dependency_overrides.clear()


def _seed_job(db, *, owner="owner-a") -> Job:
    job = Job(title="Backend", description="Python APIs", owner_sub=owner)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _fake_presign(**kwargs):
    return {
        "url": "https://staging.example",
        "fields": {
            "key": f"imports/{kwargs['batch_id']}/{kwargs['item_id']}/{kwargs['filename']}",
            "Content-Type": kwargs["content_type"],
        },
    }


def _create_uploading_batch(db, monkeypatch, job: Job) -> ImportBatch:
    monkeypatch.setattr(service.storage, "create_staging_presigned_post", _fake_presign)
    batch, _ = service.create_batch(
        db,
        owner_sub=job.owner_sub,
        job_id=job.id,
        uploads=[
            {
                "filename": "ana.pdf",
                "size_bytes": 100,
                "content_type": "application/pdf",
            }
        ],
    )
    return batch


def test_create_batch_returns_202_and_presigned_manifest(api, db_session, monkeypatch):
    client, _ = api
    job = _seed_job(db_session)
    monkeypatch.setattr(service.storage, "create_staging_presigned_post", _fake_presign)

    response = client.post(
        "/api/import-batches",
        json={
            "job_id": job.id,
            "uploads": [
                {
                    "filename": "ana.pdf",
                    "size_bytes": 100,
                    "content_type": "application/pdf",
                }
            ],
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "UPLOADING"
    assert payload["current_stage"] == "UPLOADING"
    assert payload["batch_id"]
    assert payload["uploads"][0]["upload"]["url"] == "https://staging.example"
    assert payload["expires_at"]


def test_create_batch_hides_other_owners_job(api, db_session, monkeypatch):
    client, _ = api
    job = _seed_job(db_session, owner="owner-b")
    monkeypatch.setattr(service.storage, "create_staging_presigned_post", _fake_presign)

    response = client.post(
        "/api/import-batches",
        json={
            "job_id": job.id,
            "uploads": [
                {
                    "filename": "ana.pdf",
                    "size_bytes": 100,
                    "content_type": "application/pdf",
                }
            ],
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Vacante no encontrada."}


def test_other_owner_cannot_read_batch(api, db_session):
    client, principal = api
    job = _seed_job(db_session, owner="owner-a")
    batch = ImportBatch(job_id=job.id, owner_sub="owner-a", upload_total=1)
    db_session.add(batch)
    db_session.commit()
    db_session.refresh(batch)

    principal["sub"] = "owner-b"
    response = client.get(f"/api/import-batches/{batch.id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Importacion no encontrada."}


def test_complete_is_idempotent_and_does_not_duplicate_queue_send(api, db_session, monkeypatch):
    client, _ = api
    job = _seed_job(db_session)
    batch = _create_uploading_batch(db_session, monkeypatch, job)
    monkeypatch.setattr(
        service.storage,
        "head_staging_object",
        lambda _key: {"ContentLength": 100, "ContentType": "application/pdf"},
    )
    sends: list[str] = []
    monkeypatch.setattr(service.queue, "send_import_batch", lambda batch_id: sends.append(batch_id))

    first = client.post(f"/api/import-batches/{batch.id}/complete")
    second = client.post(f"/api/import-batches/{batch.id}/complete")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "QUEUED"
    assert second.json()["status"] == "QUEUED"
    assert sends == [batch.id]


def test_queue_dispatch_failure_is_sanitized_and_batch_stays_queued(api, db_session, monkeypatch):
    client, _ = api
    job = _seed_job(db_session)
    batch = _create_uploading_batch(db_session, monkeypatch, job)
    monkeypatch.setattr(
        service.storage,
        "head_staging_object",
        lambda _key: {"ContentLength": 100, "ContentType": "application/pdf"},
    )

    def fail_send(_batch_id):
        raise RuntimeError("AWS SECRET INTERNAL PROVIDER DETAIL")

    monkeypatch.setattr(service.queue, "send_import_batch", fail_send)

    response = client.post(f"/api/import-batches/{batch.id}/complete")

    assert response.status_code == 503
    assert response.json() == {"detail": "No se pudo iniciar la importacion. Intenta de nuevo."}
    assert "AWS SECRET" not in response.text
    db_session.expire_all()
    persisted = db_session.query(ImportBatch).filter(ImportBatch.id == batch.id).one()
    assert persisted.status == "QUEUED"
    assert persisted.queue_dispatched_at is None


def test_items_are_paginated_owner_scoped_and_hide_staging_keys(api, db_session):
    client, principal = api
    job = _seed_job(db_session)
    batch = ImportBatch(job_id=job.id, owner_sub="owner-a", upload_total=1, total_items=1)
    db_session.add(batch)
    db_session.flush()
    item = ImportItem(
        batch_id=batch.id,
        kind="DOCUMENT",
        original_filename="ana.pdf",
        staging_s3_key="imports/private/secret-key.pdf",
        content_type="application/pdf",
        size_bytes=100,
        status="UPLOADED",
        current_stage="UPLOADING",
    )
    db_session.add(item)
    db_session.commit()

    response = client.get(f"/api/import-batches/{batch.id}/items?page=1&page_size=100")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["filename"] == "ana.pdf"
    assert "staging_s3_key" not in payload["items"][0]
    assert "secret-key" not in response.text

    principal["sub"] = "owner-b"
    hidden = client.get(f"/api/import-batches/{batch.id}/items?page=1&page_size=100")
    assert hidden.status_code == 404
    assert hidden.json() == {"detail": "Importacion no encontrada."}


def test_progress_payload_never_replays_presigned_or_queue_internal_fields(api, db_session):
    client, _ = api
    job = _seed_job(db_session)
    batch = ImportBatch(
        job_id=job.id,
        owner_sub="owner-a",
        upload_total=1,
        status="QUEUED",
        current_stage="UPLOADING",
        processing_token="private-token",
    )
    db_session.add(batch)
    db_session.commit()

    response = client.get(f"/api/import-batches/{batch.id}")

    assert response.status_code == 200
    payload = response.json()
    assert "uploads" not in payload
    assert "processing_token" not in payload
    assert "queue_dispatched_at" not in payload
    assert "fields" not in payload


def test_recent_batches_require_job_ownership_and_limit(api, db_session):
    client, principal = api
    job = _seed_job(db_session, owner="owner-a")
    db_session.add_all(
        [
            ImportBatch(job_id=job.id, owner_sub="owner-a", upload_total=1),
            ImportBatch(job_id=job.id, owner_sub="owner-a", upload_total=1),
        ]
    )
    db_session.commit()

    response = client.get(f"/api/import-batches?job_id={job.id}&limit=1")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1

    principal["sub"] = "owner-b"
    hidden = client.get(f"/api/import-batches?job_id={job.id}&limit=10")
    assert hidden.status_code == 404
    assert hidden.json() == {"detail": "Vacante no encontrada."}
