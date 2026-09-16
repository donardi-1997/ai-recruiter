"""Durable shared-worker boundary for provider-neutral candidate ingestion events."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_import_lease_timeout_seconds
from app.db import SessionLocal
from app.domains.candidate_ingestion import repository
from app.infrastructure.imports import queue

logger = logging.getLogger(__name__)

MAX_RECEIVE_COUNT = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def dispatch_undispatched_ingestions(db: Session) -> int:
    """Repair durable STORED ingestion events not yet checkpointed as queued."""
    dispatched = 0
    for event in repository.list_undispatched_events(db):
        try:
            queue.send_candidate_ingestion(event.id)
        except Exception:
            db.rollback()
            logger.exception(
                "Candidate ingestion queue repair failed for event %s",
                event.id,
            )
            continue
        event.queue_dispatched_at = _now()
        db.commit()
        dispatched += 1
    return dispatched


def _fail_event(db: Session, event, *, code: str, message: str) -> None:
    event.status = "FAILED"
    event.last_error_code = code
    event.last_error_message = str(message or "Candidate ingestion failed.")[:1000]
    event.completed_at = _now()
    db.commit()


def process_ingestion_event(event_id: str) -> str:
    """Claim one event. Domain processing stages are resumed from durable state."""
    token = str(uuid.uuid4())
    lease_seconds = get_import_lease_timeout_seconds()

    with SessionLocal() as db:
        event = repository.get_event(db, event_id)
        if event is None:
            return "MISSING"
        if event.status in repository.TERMINAL_INGESTION_STATUSES:
            return event.status
        if not repository.claim_event(
            db,
            event_id=event.id,
            token=token,
            lease_seconds=lease_seconds,
        ):
            return "BUSY"

    try:
        with SessionLocal() as db:
            event = repository.get_event(db, event_id)
            if event is None:
                return "MISSING"
            # The queue/lease boundary is intentionally established before the
            # document-to-candidate pipeline is introduced. A STORED event stays
            # durable and retryable until a processing stage advances it.
            return event.status
    finally:
        with SessionLocal() as db:
            repository.release_event(db, event_id=event_id, token=token)


def _mark_retry_exhausted(event_id: str) -> None:
    with SessionLocal() as db:
        event = repository.get_event(db, event_id)
        if event is None or event.status in repository.TERMINAL_INGESTION_STATUSES:
            return
        _fail_event(
            db,
            event,
            code="RETRY_EXHAUSTED",
            message="No fue posible completar la ingesta del candidato tras varios intentos.",
        )


def handle_message(message) -> None:
    """Consume one candidate-ingestion delivery without losing retry semantics."""
    try:
        outcome = process_ingestion_event(message.identifier)
    except Exception:
        logger.exception(
            "Candidate ingestion processing failed for event %s",
            message.identifier,
        )
        if int(message.receive_count) >= MAX_RECEIVE_COUNT:
            _mark_retry_exhausted(message.identifier)
        return

    # STORED/BUSY intentionally remain on SQS until the processing pipeline
    # advances them. Terminal/missing work can be acknowledged safely.
    if outcome in {"COMPLETED", "FAILED", "NEEDS_REVIEW", "MISSING"}:
        queue.delete_message(message.receipt_handle)
