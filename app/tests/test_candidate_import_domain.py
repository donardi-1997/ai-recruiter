"""Application-domain contracts for durable candidate imports."""

from __future__ import annotations

import importlib
import os
import tempfile
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.infrastructure.imports.documents import ParsedDocument
from app.models import Candidate, CandidateIdentity, ImportBatch, ImportItem, Job, JobCandidate


def _module(name: str):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        pytest.fail(f"candidate import application module is missing: {exc}")


@pytest.fixture()
def db():
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
def parsed_document_factory():
    def factory(
        *,
        name: str = "Ana Gomez",
        email: str | None = "ana@example.com",
        phone: str | None = "+573001234567",
        sha256: str | None = None,
        filename: str = "ana.pdf",
    ) -> ParsedDocument:
        return ParsedDocument(
            filename=filename,
            content_type="application/pdf" if filename.endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            display_name=name,
            email=email,
            phone=phone,
            text=f"{name}\n{email or ''}\n{phone or ''}",
            header_text=f"{name}\n{email or ''}\n{phone or ''}",
            sha256=sha256 or uuid.uuid4().hex * 2,
        )

    return factory


def _seed_job(db, *, owner: str = "owner-a") -> Job:
    job = Job(title="Backend", description="Python APIs", owner_sub=owner)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _seed_batch(db, *, owner: str = "owner-a", job: Job | None = None) -> ImportBatch:
    job = job or _seed_job(db, owner=owner)
    batch = ImportBatch(
        job_id=job.id,
        owner_sub=owner,
        status="PROCESSING",
        current_stage="DEDUPLICATING",
        upload_total=1,
        uploaded_items=1,
        total_items=1,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


def _fake_presign(**kwargs):
    filename = kwargs["filename"].replace(" ", "_")
    return {
        "url": "https://staging.example",
        "fields": {
            "key": f"imports/{kwargs['batch_id']}/{kwargs['item_id']}/{filename}",
            "Content-Type": kwargs["content_type"],
        },
    }


def test_create_batch_requires_owned_job_and_returns_upload_manifest(db, monkeypatch):
    service = _module("app.domains.candidate_imports.service")
    exceptions = _module("app.domains.candidate_imports.exceptions")
    job = _seed_job(db, owner="owner-a")
    monkeypatch.setattr(service.storage, "create_staging_presigned_post", _fake_presign)

    batch, descriptors = service.create_batch(
        db,
        owner_sub="owner-a",
        job_id=job.id,
        uploads=[
            {
                "filename": "Ana Gomez.pdf",
                "size_bytes": 100,
                "content_type": "application/pdf",
            }
        ],
    )

    assert batch.owner_sub == "owner-a"
    assert batch.job_id == job.id
    assert batch.status == "UPLOADING"
    assert batch.current_stage == "UPLOADING"
    assert batch.upload_total == 1
    assert descriptors[0]["filename"] == "Ana Gomez.pdf"
    assert descriptors[0]["upload"]["url"] == "https://staging.example"
    item = db.query(ImportItem).filter(ImportItem.batch_id == batch.id).one()
    assert item.kind == "DOCUMENT"
    assert item.staging_s3_key == descriptors[0]["upload"]["fields"]["key"]

    with pytest.raises(exceptions.JobNotFound):
        service.create_batch(
            db,
            owner_sub="owner-b",
            job_id=job.id,
            uploads=[
                {
                    "filename": "b.pdf",
                    "size_bytes": 10,
                    "content_type": "application/pdf",
                }
            ],
        )


def test_create_batch_rejects_empty_manifest_and_more_than_500_direct_documents(db, monkeypatch):
    service = _module("app.domains.candidate_imports.service")
    exceptions = _module("app.domains.candidate_imports.exceptions")
    job = _seed_job(db)
    monkeypatch.setattr(service.storage, "create_staging_presigned_post", _fake_presign)

    with pytest.raises(exceptions.InvalidImportManifest):
        service.create_batch(db, owner_sub="owner-a", job_id=job.id, uploads=[])

    uploads = [
        {"filename": f"cv-{index}.pdf", "size_bytes": 10, "content_type": "application/pdf"}
        for index in range(501)
    ]
    with pytest.raises(exceptions.InvalidImportManifest):
        service.create_batch(db, owner_sub="owner-a", job_id=job.id, uploads=uploads)


def test_create_batch_enforces_declared_file_limits(db, monkeypatch):
    service = _module("app.domains.candidate_imports.service")
    exceptions = _module("app.domains.candidate_imports.exceptions")
    job = _seed_job(db)
    monkeypatch.setattr(service.storage, "create_staging_presigned_post", _fake_presign)

    invalid_uploads = [
        {"filename": "resume.txt", "size_bytes": 10, "content_type": "text/plain"},
        {"filename": "huge.pdf", "size_bytes": 15 * 1024 * 1024 + 1, "content_type": "application/pdf"},
        {"filename": "huge.zip", "size_bytes": 500 * 1024 * 1024 + 1, "content_type": "application/zip"},
    ]
    for upload in invalid_uploads:
        with pytest.raises(exceptions.InvalidImportManifest):
            service.create_batch(
                db,
                owner_sub="owner-a",
                job_id=job.id,
                uploads=[upload],
            )


def test_complete_batch_verifies_uploads_commits_queued_then_dispatches_once(db, monkeypatch):
    service = _module("app.domains.candidate_imports.service")
    job = _seed_job(db)
    monkeypatch.setattr(service.storage, "create_staging_presigned_post", _fake_presign)
    batch, _ = service.create_batch(
        db,
        owner_sub="owner-a",
        job_id=job.id,
        uploads=[{"filename": "ana.pdf", "size_bytes": 100, "content_type": "application/pdf"}],
    )
    monkeypatch.setattr(
        service.storage,
        "head_staging_object",
        lambda key: {"ContentLength": 100, "ContentType": "application/pdf"},
    )
    sent: list[str] = []
    monkeypatch.setattr(service.queue, "send_import_batch", lambda batch_id: sent.append(batch_id))

    completed = service.complete_batch_uploads(db, owner_sub="owner-a", batch_id=batch.id)

    assert completed.status == "QUEUED"
    assert completed.current_stage == "UPLOADING"
    assert completed.uploaded_items == 1
    assert completed.queue_dispatched_at is not None
    assert sent == [batch.id]
    item = db.query(ImportItem).filter(ImportItem.batch_id == batch.id).one()
    assert item.status == "UPLOADED"

    service.complete_batch_uploads(db, owner_sub="owner-a", batch_id=batch.id)
    assert sent == [batch.id]


def test_complete_batch_size_mismatch_does_not_queue(db, monkeypatch):
    service = _module("app.domains.candidate_imports.service")
    exceptions = _module("app.domains.candidate_imports.exceptions")
    job = _seed_job(db)
    monkeypatch.setattr(service.storage, "create_staging_presigned_post", _fake_presign)
    batch, _ = service.create_batch(
        db,
        owner_sub="owner-a",
        job_id=job.id,
        uploads=[{"filename": "ana.pdf", "size_bytes": 100, "content_type": "application/pdf"}],
    )
    monkeypatch.setattr(service.storage, "head_staging_object", lambda key: {"ContentLength": 99})

    with pytest.raises(exceptions.UploadVerificationFailed):
        service.complete_batch_uploads(db, owner_sub="owner-a", batch_id=batch.id)

    db.expire_all()
    persisted = db.query(ImportBatch).filter(ImportBatch.id == batch.id).one()
    assert persisted.status == "UPLOADING"
    assert persisted.queue_dispatched_at is None


def test_queue_send_failure_leaves_durable_queued_batch_for_repair(db, monkeypatch):
    service = _module("app.domains.candidate_imports.service")
    exceptions = _module("app.domains.candidate_imports.exceptions")
    job = _seed_job(db)
    monkeypatch.setattr(service.storage, "create_staging_presigned_post", _fake_presign)
    batch, _ = service.create_batch(
        db,
        owner_sub="owner-a",
        job_id=job.id,
        uploads=[{"filename": "ana.pdf", "size_bytes": 100, "content_type": "application/pdf"}],
    )
    monkeypatch.setattr(service.storage, "head_staging_object", lambda key: {"ContentLength": 100})

    def fail_send(_batch_id):
        raise RuntimeError("provider detail must not escape")

    monkeypatch.setattr(service.queue, "send_import_batch", fail_send)

    with pytest.raises(exceptions.QueueDispatchFailed, match="QUEUE_DISPATCH_FAILED"):
        service.complete_batch_uploads(db, owner_sub="owner-a", batch_id=batch.id)

    db.expire_all()
    persisted = db.query(ImportBatch).filter(ImportBatch.id == batch.id).one()
    assert persisted.status == "QUEUED"
    assert persisted.uploaded_items == 1
    assert persisted.queue_dispatched_at is None


def test_batch_reads_and_items_are_owner_scoped(db):
    service = _module("app.domains.candidate_imports.service")
    exceptions = _module("app.domains.candidate_imports.exceptions")
    batch = _seed_batch(db, owner="owner-a")
    item = ImportItem(
        batch_id=batch.id,
        kind="DOCUMENT",
        original_filename="ana.pdf",
        staging_s3_key="imports/a",
        content_type="application/pdf",
        size_bytes=10,
        status="UPLOADED",
        current_stage="UPLOADING",
    )
    db.add(item)
    db.commit()

    assert service.get_batch(db, owner_sub="owner-a", batch_id=batch.id).id == batch.id
    items, total = service.list_batch_items(
        db,
        owner_sub="owner-a",
        batch_id=batch.id,
        page=1,
        page_size=100,
    )
    assert total == 1
    assert items[0].id == item.id

    with pytest.raises(exceptions.ImportBatchNotFound):
        service.get_batch(db, owner_sub="owner-b", batch_id=batch.id)
    with pytest.raises(exceptions.ImportBatchNotFound):
        service.list_batch_items(
            db,
            owner_sub="owner-b",
            batch_id=batch.id,
            page=1,
            page_size=100,
        )


def test_recent_batches_require_owned_job(db):
    service = _module("app.domains.candidate_imports.service")
    exceptions = _module("app.domains.candidate_imports.exceptions")
    job = _seed_job(db, owner="owner-a")
    first = ImportBatch(job_id=job.id, owner_sub="owner-a", upload_total=1)
    second = ImportBatch(job_id=job.id, owner_sub="owner-a", upload_total=1)
    db.add_all([first, second])
    db.commit()

    recent = service.list_recent_batches(
        db,
        owner_sub="owner-a",
        job_id=job.id,
        limit=1,
    )
    assert len(recent) == 1
    assert recent[0].owner_sub == "owner-a"

    with pytest.raises(exceptions.JobNotFound):
        service.list_recent_batches(db, owner_sub="owner-b", job_id=job.id, limit=10)


def test_name_only_never_reuses_candidate(db, parsed_document_factory):
    service = _module("app.domains.candidate_imports.service")
    batch = _seed_batch(db)
    existing = Candidate(name="Ana Gomez", email=None, owner_sub="owner-a")
    db.add(existing)
    db.commit()

    candidate, outcome = service.resolve_or_create_candidate(
        db,
        owner_sub="owner-a",
        parsed_document=parsed_document_factory(name="Ana Gomez", email=None, phone=None),
        batch_id=batch.id,
    )

    assert outcome == "CREATED"
    assert candidate.id != existing.id


def test_same_document_hash_reuses_candidate_and_assigns_job(db, parsed_document_factory):
    service = _module("app.domains.candidate_imports.service")
    batch = _seed_batch(db)
    document = parsed_document_factory(sha256="a" * 64)

    first, first_outcome = service.resolve_or_create_candidate(
        db,
        owner_sub="owner-a",
        parsed_document=document,
        batch_id=batch.id,
    )
    second, second_outcome = service.resolve_or_create_candidate(
        db,
        owner_sub="owner-a",
        parsed_document=document,
        batch_id=batch.id,
    )

    assert first_outcome == "CREATED"
    assert second_outcome == "REUSED"
    assert second.id == first.id
    links = db.query(JobCandidate).filter(
        JobCandidate.job_id == batch.job_id,
        JobCandidate.candidate_id == first.id,
    ).all()
    assert len(links) == 1
    kinds = {
        identity.kind
        for identity in db.query(CandidateIdentity).filter(CandidateIdentity.candidate_id == first.id).all()
    }
    assert kinds == {"DOCUMENT_SHA256", "EMAIL", "PHONE"}


def test_legacy_email_match_reuses_candidate_and_bootstraps_identities(db, parsed_document_factory):
    service = _module("app.domains.candidate_imports.service")
    batch = _seed_batch(db)
    existing = Candidate(
        name="Ana Antigua",
        email="  Ana@Example.COM ",
        owner_sub="owner-a",
        metadata_={"filename": "old.pdf"},
    )
    db.add(existing)
    db.commit()

    candidate, outcome = service.resolve_or_create_candidate(
        db,
        owner_sub="owner-a",
        parsed_document=parsed_document_factory(
            name="Ana Gomez",
            email="ana@example.com",
            phone=None,
            sha256="b" * 64,
            filename="new.pdf",
        ),
        batch_id=batch.id,
    )

    assert outcome == "REUSED"
    assert candidate.id == existing.id
    assert candidate.metadata_["filename"] == "new.pdf"
    values = {
        (identity.kind, identity.value)
        for identity in db.query(CandidateIdentity).filter(CandidateIdentity.candidate_id == existing.id).all()
    }
    assert ("EMAIL", "ana@example.com") in values
    assert ("DOCUMENT_SHA256", "b" * 64) in values


def test_reused_candidate_does_not_overwrite_different_existing_email(db, parsed_document_factory):
    service = _module("app.domains.candidate_imports.service")
    batch = _seed_batch(db)
    existing = Candidate(name="Ana", email="old@example.com", owner_sub="owner-a")
    db.add(existing)
    db.commit()
    db.add(
        CandidateIdentity(
            owner_sub="owner-a",
            candidate_id=existing.id,
            kind="PHONE",
            value="+573001234567",
        )
    )
    db.commit()

    candidate, outcome = service.resolve_or_create_candidate(
        db,
        owner_sub="owner-a",
        parsed_document=parsed_document_factory(
            email="new@example.com",
            phone="+573001234567",
            sha256="c" * 64,
        ),
        batch_id=batch.id,
    )

    assert outcome == "REUSED"
    assert candidate.id == existing.id
    assert candidate.email == "old@example.com"
    assert db.query(CandidateIdentity).filter(
        CandidateIdentity.owner_sub == "owner-a",
        CandidateIdentity.kind == "EMAIL",
        CandidateIdentity.value == "new@example.com",
        CandidateIdentity.candidate_id == existing.id,
    ).one_or_none() is not None


def test_conflicting_strong_identities_never_merge_candidates(db, parsed_document_factory):
    service = _module("app.domains.candidate_imports.service")
    exceptions = _module("app.domains.candidate_imports.exceptions")
    batch = _seed_batch(db)
    a = Candidate(name="A", owner_sub="owner-a")
    b = Candidate(name="B", owner_sub="owner-a")
    db.add_all([a, b])
    db.commit()
    db.add_all(
        [
            CandidateIdentity(
                owner_sub="owner-a",
                candidate_id=a.id,
                kind="EMAIL",
                value="ana@example.com",
            ),
            CandidateIdentity(
                owner_sub="owner-a",
                candidate_id=b.id,
                kind="PHONE",
                value="+573001234567",
            ),
        ]
    )
    db.commit()

    with pytest.raises(exceptions.IdentityConflict, match="IDENTITY_CONFLICT"):
        service.resolve_or_create_candidate(
            db,
            owner_sub="owner-a",
            parsed_document=parsed_document_factory(
                email="ana@example.com",
                phone="+573001234567",
            ),
            batch_id=batch.id,
        )


def test_ambiguous_legacy_email_is_identity_conflict(db, parsed_document_factory):
    service = _module("app.domains.candidate_imports.service")
    exceptions = _module("app.domains.candidate_imports.exceptions")
    batch = _seed_batch(db)
    db.add_all(
        [
            Candidate(name="A", email="Ana@Example.com", owner_sub="owner-a"),
            Candidate(name="B", email=" ana@example.COM ", owner_sub="owner-a"),
        ]
    )
    db.commit()

    with pytest.raises(exceptions.IdentityConflict, match="IDENTITY_CONFLICT"):
        service.resolve_or_create_candidate(
            db,
            owner_sub="owner-a",
            parsed_document=parsed_document_factory(
                email="ana@example.com",
                phone=None,
            ),
            batch_id=batch.id,
        )


def test_identity_resolution_is_tenant_scoped(db, parsed_document_factory):
    service = _module("app.domains.candidate_imports.service")
    batch = _seed_batch(db, owner="owner-a")
    other = Candidate(name="Other", owner_sub="owner-b")
    db.add(other)
    db.commit()
    db.add(
        CandidateIdentity(
            owner_sub="owner-b",
            candidate_id=other.id,
            kind="EMAIL",
            value="ana@example.com",
        )
    )
    db.commit()

    candidate, outcome = service.resolve_or_create_candidate(
        db,
        owner_sub="owner-a",
        parsed_document=parsed_document_factory(email="ana@example.com", phone=None),
        batch_id=batch.id,
    )

    assert outcome == "CREATED"
    assert candidate.owner_sub == "owner-a"
    assert candidate.id != other.id


def test_presenters_never_expose_internal_queue_or_staging_state(db):
    presenter = _module("app.domains.candidate_imports.presenter")
    batch = _seed_batch(db)
    batch.processing_token = "secret-token"
    batch.queue_dispatched_at = datetime.now(timezone.utc)
    batch.last_error_code = "SAFE_CODE"
    batch.last_error_message = "Mensaje seguro."
    item = ImportItem(
        batch_id=batch.id,
        kind="DOCUMENT",
        original_filename="ana.pdf",
        staging_s3_key="private/staging/key",
        content_type="application/pdf",
        size_bytes=10,
        status="PROCESSING",
        current_stage="DEDUPLICATING",
    )
    db.add(item)
    db.commit()

    batch_payload = presenter.batch_progress_payload(batch)
    item_payload = presenter.import_item_payload(item)

    assert batch_payload["id"] == batch.id
    assert batch_payload["last_error_code"] == "SAFE_CODE"
    assert "processing_token" not in batch_payload
    assert "queue_dispatched_at" not in batch_payload
    assert "staging_s3_key" not in item_payload
    assert item_payload["filename"] == "ana.pdf"
