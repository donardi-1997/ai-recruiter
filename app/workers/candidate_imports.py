"""Durable SQS worker boundary for candidate-import batches."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.domains.candidate_imports import repository, service as import_service
from app.domains.candidate_imports.exceptions import IdentityConflict
from app.infrastructure.imports import documents, ingestion, queue, storage
from app.infrastructure.imports.documents import DocumentImportError
from app.infrastructure.imports.queue import ReceivedImportMessage

logger = logging.getLogger(__name__)

MAX_RECEIVE_COUNT = 5
MAX_BATCH_DOCUMENTS = 500
MAX_BATCH_EXPANDED_BYTES = 1024 * 1024 * 1024
DEFAULT_INGESTION_POLL_SECONDS = 5
DEFAULT_INGESTION_TIMEOUT_SECONDS = 30 * 60
PUBLIC_RETRY_EXHAUSTED_MESSAGE = (
    "No fue posible completar la importacion. Intenta nuevamente."
)
PUBLIC_ITEM_FAILURE_MESSAGE = "No fue posible procesar este documento."
PUBLIC_INGESTION_FAILURE_MESSAGE = (
    "No fue posible indexar los documentos del lote. Intenta nuevamente."
)


class BatchMissing(Exception):
    """The queued batch was deleted before its SQS message was consumed."""


class LeaseKeeper:
    """Refresh the durable DB lease and SQS visibility for one active batch."""

    def __init__(
        self,
        *,
        batch_id: str,
        token: str,
        receipt_handle: str | None,
        interval_seconds: int = 60,
        visibility_seconds: int = 300,
    ) -> None:
        self.batch_id = batch_id
        self.token = token
        self.receipt_handle = receipt_handle
        self.interval_seconds = interval_seconds
        self.visibility_seconds = visibility_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def beat_once(self) -> None:
        """Refresh heartbeat and visibility only while this token still owns the lease."""
        with SessionLocal() as db:
            repository.heartbeat_batch(
                db,
                batch_id=self.batch_id,
                token=self.token,
                now=datetime.now(timezone.utc),
            )
            batch = repository.get_batch_for_worker(db, self.batch_id)
            if batch is None or batch.processing_token != self.token:
                return

        if self.receipt_handle:
            queue.extend_visibility(
                self.receipt_handle,
                self.visibility_seconds,
            )

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            try:
                self.beat_once()
            except Exception:
                logger.exception(
                    "Candidate import lease heartbeat failed for batch %s",
                    self.batch_id,
                )

    def start(self) -> None:
        """Start the daemon heartbeat loop once."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"candidate-import-lease-{self.batch_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop and join the heartbeat loop before returning."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1, self.interval_seconds + 1))


def dispatch_undispatched_batches(db: Session) -> int:
    """Repair durable QUEUED batches that were not checkpointed as dispatched."""
    dispatched = 0
    batches = repository.list_undispatched_queued_batches(db)
    for batch in batches:
        try:
            queue.send_import_batch(batch.id)
        except Exception:
            db.rollback()
            logger.exception(
                "Candidate import queue repair failed for batch %s",
                batch.id,
            )
            continue

        batch.queue_dispatched_at = datetime.now(timezone.utc)
        db.commit()
        dispatched += 1
    return dispatched


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _identity_created_during_batch(batch, identity) -> bool:
    if identity is None or batch.started_at is None:
        return False
    created_at = _as_utc(identity.created_at)
    started_at = _as_utc(batch.started_at)
    return bool(created_at and started_at and created_at >= started_at)


def _identity_was_created_in_batch(db: Session, batch, item) -> bool:
    """Infer whether a successful item's document identity is new to this batch."""
    if not item.candidate_id or not item.document_sha256 or batch.started_at is None:
        return False
    identity = repository.find_identity(
        db,
        owner_sub=batch.owner_sub,
        kind="DOCUMENT_SHA256",
        value=item.document_sha256.casefold(),
    )
    if identity is None or identity.candidate_id != item.candidate_id:
        return False
    return _identity_created_during_batch(batch, identity)


def _canonicalized_candidate_ids(db: Session, batch) -> set[str]:
    """Recover canonical updates already checkpointed before a worker restart."""
    candidate_ids: set[str] = set()
    for item in repository.list_items_for_worker(
        db,
        batch_id=batch.id,
        kind="DOCUMENT",
    ):
        if item.status != "COMPLETED":
            continue
        if _identity_was_created_in_batch(db, batch, item):
            candidate_ids.add(item.candidate_id)
    return candidate_ids


def _batch_has_canonical_changes(db: Session, batch) -> bool:
    """Return whether a completed document identity was created by this batch."""
    return bool(_canonicalized_candidate_ids(db, batch))


def _expand_archives_once(db: Session, batch) -> None:
    """Persist ZIP children to staging and checkpoint the container exactly once."""
    document_items = repository.list_items_for_worker(
        db,
        batch_id=batch.id,
        kind="DOCUMENT",
    )
    discovered_documents = len(document_items)
    discovered_bytes = sum(max(0, int(item.size_bytes or 0)) for item in document_items)

    for archive in repository.list_items_for_worker(
        db,
        batch_id=batch.id,
        kind="ARCHIVE",
    ):
        if archive.status in {"COMPLETED", "FAILED"}:
            continue

        archive.status = "PROCESSING"
        archive.current_stage = "VALIDATING"
        db.commit()

        try:
            payload = storage.read_staging_object(archive.staging_s3_key)
            expanded = documents.expand_zip(
                payload,
                remaining_documents=max(0, MAX_BATCH_DOCUMENTS - discovered_documents),
                remaining_bytes=max(0, MAX_BATCH_EXPANDED_BYTES - discovered_bytes),
            )

            created_children = []
            for child in expanded:
                child_id = str(uuid.uuid4())
                staging_key = storage.write_staging_child(
                    batch_id=batch.id,
                    item_id=child_id,
                    filename=child.filename,
                    data=child.data,
                    content_type=child.content_type,
                )
                child_item = repository.create_item(
                    db,
                    item_id=child_id,
                    batch_id=batch.id,
                    parent_item_id=archive.id,
                    kind="DOCUMENT",
                    original_filename=child.filename,
                    staging_s3_key=staging_key,
                    content_type=child.content_type,
                    size_bytes=len(child.data),
                )
                child_item.status = "UPLOADED"
                child_item.current_stage = "VALIDATING"
                created_children.append(child_item)

            archive.status = "COMPLETED"
            archive.current_stage = "VALIDATING"
            archive.completed_at = datetime.now(timezone.utc)
            discovered_documents += len(created_children)
            discovered_bytes += sum(item.size_bytes for item in created_children)
            batch.total_items = discovered_documents
            db.commit()
        except Exception:
            db.rollback()
            raise


def _mark_document_failed(
    db: Session,
    *,
    batch_id: str,
    item_id: str,
    error_code: str,
) -> None:
    """Checkpoint one public-safe item failure without failing the whole batch."""
    db.rollback()
    batch = repository.get_batch_for_worker(db, batch_id)
    item = repository.get_item_for_worker(
        db,
        batch_id=batch_id,
        item_id=item_id,
    )
    if batch is None or item is None or item.status in {"COMPLETED", "FAILED"}:
        return

    item.status = "FAILED"
    item.current_stage = "DEDUPLICATING"
    item.error_code = error_code
    item.error_message = PUBLIC_ITEM_FAILURE_MESSAGE
    item.completed_at = datetime.now(timezone.utc)
    batch.processed_items += 1
    batch.failed_items += 1
    db.commit()


def _prepare_batch_documents(db: Session, batch) -> None:
    """Expand, parse, deduplicate and checkpoint all document items idempotently."""
    if batch is None:
        raise BatchMissing()
    if batch.status in repository.TERMINAL_BATCH_STATUSES:
        return

    batch.status = "PROCESSING"
    batch.current_stage = "VALIDATING"
    db.commit()

    _expand_archives_once(db, batch)

    batch = repository.get_batch_for_worker(db, batch.id)
    if batch is None:
        raise BatchMissing()
    batch.status = "PROCESSING"
    batch.current_stage = "DEDUPLICATING"
    db.commit()

    canonicalized = _canonicalized_candidate_ids(db, batch)
    document_items = repository.list_items_for_worker(
        db,
        batch_id=batch.id,
        kind="DOCUMENT",
    )

    for document_item in document_items:
        if document_item.status in {"COMPLETED", "FAILED"}:
            continue

        item_id = document_item.id
        try:
            document_item.status = "PROCESSING"
            document_item.current_stage = "DEDUPLICATING"
            db.commit()

            data = storage.read_staging_object(document_item.staging_s3_key)
            parsed = documents.extract_document(data, document_item.original_filename)
            preexisting_hash_identity = repository.find_identity(
                db,
                owner_sub=batch.owner_sub,
                kind="DOCUMENT_SHA256",
                value=parsed.sha256.casefold(),
            )

            candidate, outcome = import_service.resolve_or_create_candidate(
                db,
                owner_sub=batch.owner_sub,
                parsed_document=parsed,
                batch_id=batch.id,
            )

            hash_is_old = (
                preexisting_hash_identity is not None
                and not _identity_created_during_batch(batch, preexisting_hash_identity)
            )
            should_write_canonical = (
                candidate.id not in canonicalized and not hash_is_old
            )
            if should_write_canonical:
                canonical_result = storage.write_canonical_candidate_document(
                    candidate_id=candidate.id,
                    candidate_name=candidate.name,
                    filename=parsed.filename,
                    data=data,
                    sha256=parsed.sha256,
                )
                if canonical_result.changed:
                    canonicalized.add(candidate.id)

            batch = repository.get_batch_for_worker(db, batch.id)
            item = repository.get_item_for_worker(
                db,
                batch_id=batch.id,
                item_id=item_id,
            )
            if batch is None or item is None:
                raise BatchMissing()

            item.document_sha256 = parsed.sha256
            item.candidate_id = candidate.id
            item.outcome = outcome
            item.status = "COMPLETED"
            item.current_stage = "DEDUPLICATING"
            item.error_code = None
            item.error_message = None
            item.completed_at = datetime.now(timezone.utc)
            batch.processed_items += 1
            batch.successful_items += 1
            if outcome == "REUSED":
                batch.reused_items += 1
            db.commit()
        except IdentityConflict:
            _mark_document_failed(
                db,
                batch_id=batch.id,
                item_id=item_id,
                error_code="IDENTITY_CONFLICT",
            )
            batch = repository.get_batch_for_worker(db, batch.id)
        except DocumentImportError as exc:
            error_code = str(exc).split(":", 1)[0].strip() or "INVALID_DOCUMENT"
            _mark_document_failed(
                db,
                batch_id=batch.id,
                item_id=item_id,
                error_code=error_code,
            )
            batch = repository.get_batch_for_worker(db, batch.id)
        except Exception:
            db.rollback()
            raise


def _fail_batch(
    db: Session,
    batch,
    *,
    error_code: str,
    error_message: str,
) -> None:
    """Persist a terminal batch failure without leaking provider internals."""
    batch.status = "FAILED"
    batch.last_error_code = error_code
    batch.last_error_message = error_message
    batch.completed_at = datetime.now(timezone.utc)
    batch.processing_token = None
    batch.heartbeat_at = None
    db.commit()


def _run_ingestion_stage(
    db: Session,
    batch,
    *,
    poll_interval_seconds: float = DEFAULT_INGESTION_POLL_SECONDS,
    timeout_seconds: float = DEFAULT_INGESTION_TIMEOUT_SECONDS,
) -> None:
    """Run or resume the single logical Bedrock ingestion for one batch."""
    if batch is None:
        raise BatchMissing()
    if batch.status in repository.TERMINAL_BATCH_STATUSES:
        return
    if batch.current_stage not in {"DEDUPLICATING", "INGESTING"}:
        return

    if batch.current_stage == "DEDUPLICATING":
        if not _batch_has_canonical_changes(db, batch):
            batch.status = "PROCESSING"
            batch.current_stage = "EVALUATING"
            db.commit()
            return
        batch.status = "PROCESSING"
        batch.current_stage = "INGESTING"
        db.commit()

    if not batch.bedrock_ingestion_job_id:
        job_id, _initial_status = ingestion.start_batch_ingestion(batch.id)
        batch.bedrock_ingestion_job_id = job_id
        db.commit()
        db.refresh(batch)

    job_id = batch.bedrock_ingestion_job_id
    deadline = time.monotonic() + max(0.0, timeout_seconds)

    while True:
        status = ingestion.get_ingestion_status(job_id).upper()
        if status == "COMPLETE":
            batch.status = "PROCESSING"
            batch.current_stage = "EVALUATING"
            db.commit()
            return
        if status in {"FAILED", "STOPPED"}:
            _fail_batch(
                db,
                batch,
                error_code="BEDROCK_INGESTION_FAILED",
                error_message=PUBLIC_INGESTION_FAILURE_MESSAGE,
            )
            return
        if timeout_seconds <= 0 or time.monotonic() >= deadline:
            _fail_batch(
                db,
                batch,
                error_code="BEDROCK_INGESTION_TIMEOUT",
                error_message=PUBLIC_INGESTION_FAILURE_MESSAGE,
            )
            return

        time.sleep(max(0.0, poll_interval_seconds))


def _mark_retry_exhausted(batch_id: str) -> None:
    """Persist a public-safe terminal failure while preserving the failed stage."""
    with SessionLocal() as db:
        batch = repository.get_batch_for_worker(db, batch_id)
        if batch is None or batch.status in repository.TERMINAL_BATCH_STATUSES:
            return

        _fail_batch(
            db,
            batch,
            error_code="IMPORT_RETRY_EXHAUSTED",
            error_message=PUBLIC_RETRY_EXHAUSTED_MESSAGE,
        )


def process_batch(batch_id: str, *, receipt_handle: str | None = None) -> None:
    """Process one durable import batch.

    The queue/lease boundary is intentionally established before the pipeline
    stages are added. Until the remaining stages are implemented, a prepared
    batch remains unacknowledged rather than being falsely completed.
    """
    with SessionLocal() as db:
        batch = repository.get_batch_for_worker(db, batch_id)
        if batch is None:
            raise BatchMissing(batch_id)
        if batch.status in repository.TERMINAL_BATCH_STATUSES:
            return

    raise NotImplementedError("candidate import pipeline stages are not implemented yet")


def handle_message(message: ReceivedImportMessage) -> None:
    """Handle one SQS delivery with safe ACK/DLQ semantics."""
    try:
        process_batch(
            message.batch_id,
            receipt_handle=message.receipt_handle,
        )
    except BatchMissing:
        queue.delete_message(message.receipt_handle)
        return
    except Exception:
        logger.exception(
            "Candidate import worker failed for batch %s on receive %s",
            message.batch_id,
            message.receive_count,
        )
        if message.receive_count >= MAX_RECEIVE_COUNT:
            _mark_retry_exhausted(message.batch_id)
        # Do not ACK failures: SQS visibility/redrive policy owns the retry/DLQ.
        return

    queue.delete_message(message.receipt_handle)


def run_worker_forever() -> None:
    """Long-poll SQS forever, repairing undispatched durable batches each cycle."""
    while True:
        try:
            with SessionLocal() as db:
                dispatch_undispatched_batches(db)
        except Exception:
            logger.exception("Candidate import queue repair cycle failed")

        for message in queue.receive_import_messages():
            handle_message(message)


if __name__ == "__main__":
    run_worker_forever()
