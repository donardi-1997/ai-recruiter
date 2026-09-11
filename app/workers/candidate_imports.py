"""Durable SQS worker boundary for candidate-import batches."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.domains.candidate_imports import repository
from app.infrastructure.imports import queue
from app.infrastructure.imports.queue import ReceivedImportMessage

logger = logging.getLogger(__name__)

MAX_RECEIVE_COUNT = 5
PUBLIC_RETRY_EXHAUSTED_MESSAGE = (
    "No fue posible completar la importacion. Intenta nuevamente."
)


class BatchMissing(Exception):
    """The queued batch was deleted before its SQS message was consumed."""


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


def _mark_retry_exhausted(batch_id: str) -> None:
    """Persist a public-safe terminal failure while preserving the failed stage."""
    with SessionLocal() as db:
        batch = repository.get_batch_for_worker(db, batch_id)
        if batch is None or batch.status in repository.TERMINAL_BATCH_STATUSES:
            return

        batch.status = "FAILED"
        batch.last_error_code = "IMPORT_RETRY_EXHAUSTED"
        batch.last_error_message = PUBLIC_RETRY_EXHAUSTED_MESSAGE
        batch.completed_at = datetime.now(timezone.utc)
        batch.processing_token = None
        batch.heartbeat_at = None
        db.commit()


def process_batch(batch_id: str, *, receipt_handle: str | None = None) -> None:
    """Process one durable import batch.

    The queue/lease boundary is intentionally established before the pipeline
    stages are added. Until the stage implementation is present, existing
    batches remain unacknowledged rather than being falsely completed.
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
