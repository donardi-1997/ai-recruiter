"""Durable shared-worker pipeline for provider-neutral candidate ingestion events."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_import_lease_timeout_seconds
from app.db import SessionLocal
from app.domains.candidate_ingestion import job_resolution, repository
from app.domains.candidates import identity as candidate_identity
from app.domains.candidates import repository as candidates_repository
from app.domains.evaluations import service as evaluations_service
from app.domains.ranking import service as ranking_service
from app.domains.ranking.exceptions import RankingAlreadyRunning, RankingJobNotFound
from app.infrastructure.imports import documents, ingestion, queue, storage
from app.infrastructure.imports.documents import DocumentImportError

logger = logging.getLogger(__name__)

MAX_RECEIVE_COUNT = 5
DEFAULT_INGESTION_POLL_SECONDS = 5
DEFAULT_INGESTION_TIMEOUT_SECONDS = 30 * 60
TRANSIENT_EVALUATION_ERRORS = (
    "ThrottlingException",
    "TooManyRequestsException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
    "InternalServerException",
)
EVALUATION_RETRY_DELAYS = (1, 2, 4)
RANKING_RETRY_DELAYS = (1, 2, 4)


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


def _safe_message(message: str, fallback: str) -> str:
    value = str(message or "").strip()
    lowered = value.casefold()
    if not value or "http://" in lowered or "https://" in lowered or "x-amz-" in lowered:
        return fallback
    return value[:1000]


def _fail_event(db: Session, event, *, code: str, message: str) -> None:
    event.status = "FAILED"
    event.last_error_code = code
    event.last_error_message = _safe_message(
        message,
        "No fue posible procesar la ingesta del candidato.",
    )
    event.completed_at = _now()
    db.commit()


def _needs_review(db: Session, event, *, code: str, message: str) -> str:
    event.status = "NEEDS_REVIEW"
    event.last_error_code = code
    event.last_error_message = _safe_message(
        message,
        "La ingesta requiere revision manual.",
    )
    event.completed_at = _now()
    db.commit()
    return event.status


def _prepare_document(db: Session, event) -> str | None:
    """Parse, resolve identity, canonicalize and resolve one deterministic job."""
    event_documents = repository.list_documents(db, event_id=event.id)
    if not event_documents:
        return _needs_review(
            db,
            event,
            code="RESUME_ATTACHMENT_MISSING",
            message="No se encontro un CV utilizable.",
        )
    if len(event_documents) != 1:
        return _needs_review(
            db,
            event,
            code="MULTIPLE_RESUME_ATTACHMENTS",
            message="Se encontraron varios documentos posibles para el candidato.",
        )

    document = event_documents[0]
    try:
        data = storage.read_staging_object(document.source_s3_key)
        parsed = documents.extract_document(data, document.filename)
    except DocumentImportError as exc:
        return _needs_review(
            db,
            event,
            code=str(exc).split(":", 1)[0] or "INVALID_DOCUMENT",
            message="El documento recibido no pudo interpretarse como CV.",
        )

    try:
        if event.candidate_id:
            candidate = candidates_repository.get_candidate(
                db,
                event.candidate_id,
                owner_sub=event.owner_sub,
            )
            if candidate is None:
                return _needs_review(
                    db,
                    event,
                    code="CANDIDATE_UNRESOLVED",
                    message="El candidato preasignado ya no esta disponible.",
                )
        else:
            candidate, _outcome = candidate_identity.resolve_or_create_candidate(
                db,
                owner_sub=event.owner_sub,
                parsed_document=parsed,
            )
    except candidate_identity.CandidateIdentityConflict:
        return _needs_review(
            db,
            event,
            code="IDENTITY_CONFLICT",
            message="Las identidades del documento coinciden con candidatos diferentes.",
        )

    written = storage.write_canonical_candidate_document(
        candidate_id=candidate.id,
        candidate_name=candidate.name,
        filename=parsed.filename,
        data=data,
        sha256=parsed.sha256,
    )
    document.document_sha256 = parsed.sha256
    document.canonical_s3_key = written.key
    document.status = "COMPLETED"
    document.completed_at = _now()
    event.candidate_id = candidate.id

    job = job_resolution.resolve_job(
        db,
        owner_sub=event.owner_sub,
        explicit_job_id=event.job_id,
        metadata=event.raw_metadata,
    )
    if job is None:
        db.commit()
        return _needs_review(
            db,
            event,
            code="JOB_UNRESOLVED",
            message="No fue posible asociar el candidato a una unica vacante.",
        )

    candidates_repository.ensure_candidate_assigned_to_job(
        db,
        job_id=job.id,
        candidate_id=candidate.id,
    )
    event.job_id = job.id
    event.status = "INGESTING"
    event.last_error_code = None
    event.last_error_message = None
    db.commit()
    return None


def _poll_bedrock(db: Session, event) -> bool:
    docs = repository.list_documents(db, event_id=event.id)
    if len(docs) != 1 or not docs[0].document_sha256:
        _fail_event(
            db,
            event,
            code="CANONICAL_DOCUMENT_MISSING",
            message="No existe un CV canonico listo para indexar.",
        )
        return False

    document_sha256 = docs[0].document_sha256
    event.status = "INGESTING"
    db.commit()

    if not event.bedrock_ingestion_job_id:
        try:
            bedrock_id, _status = ingestion.start_ingestion(
                operation_key=f"candidate-ingestion:{event.id}:{document_sha256}",
                description=f"candidate-ingestion:{event.id}:{document_sha256[:12]}",
            )
        except Exception as exc:
            _fail_event(
                db,
                event,
                code="BEDROCK_INGESTION_FAILED",
                message=str(exc),
            )
            return False
        event.bedrock_ingestion_job_id = bedrock_id
        db.commit()

    deadline = time.monotonic() + DEFAULT_INGESTION_TIMEOUT_SECONDS
    while True:
        try:
            status = str(
                ingestion.get_ingestion_status(event.bedrock_ingestion_job_id)
            ).upper()
        except Exception as exc:
            _fail_event(
                db,
                event,
                code="BEDROCK_INGESTION_FAILED",
                message=str(exc),
            )
            return False

        if status == "COMPLETE":
            event.status = "EVALUATING"
            db.commit()
            return True
        if status in {"FAILED", "STOPPED"}:
            _fail_event(
                db,
                event,
                code="BEDROCK_INGESTION_FAILED",
                message="La indexacion del CV no pudo completarse.",
            )
            return False
        if time.monotonic() >= deadline:
            _fail_event(
                db,
                event,
                code="BEDROCK_INGESTION_TIMEOUT",
                message="La indexacion del CV excedio el tiempo permitido.",
            )
            return False
        time.sleep(DEFAULT_INGESTION_POLL_SECONDS)


def _is_transient_evaluation_error(message: str | None) -> bool:
    value = str(message or "")
    return any(marker in value for marker in TRANSIENT_EVALUATION_ERRORS)


def _evaluate(db: Session, event) -> bool:
    if not event.candidate_id or not event.job_id:
        _fail_event(
            db,
            event,
            code="CANDIDATE_CONTEXT_MISSING",
            message="El candidato o la vacante no estan disponibles.",
        )
        return False

    event.status = "EVALUATING"
    db.commit()
    last_error = None
    delays = (0,) + EVALUATION_RETRY_DELAYS
    for index, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            evaluation, _newly_evaluated, internal_error = (
                evaluations_service.evaluate_candidate_for_owner(
                    db,
                    candidate_id=event.candidate_id,
                    job_id=event.job_id,
                    owner_sub=event.owner_sub,
                )
            )
        except evaluations_service.EvaluationCriteriaMissing:
            _needs_review(
                db,
                event,
                code="JOB_EVALUATION_CRITERIA_MISSING",
                message=(
                    "La vacante necesita descripción o criterios aprobados "
                    "antes de evaluar candidatos."
                ),
            )
            return False
        if getattr(evaluation, "status", None) == "COMPLETED" and not internal_error:
            event.status = "RANKING"
            db.commit()
            return True

        last_error = internal_error or getattr(evaluation, "error_message", None)
        if not _is_transient_evaluation_error(last_error) or index == len(delays) - 1:
            break

    _fail_event(
        db,
        event,
        code="EVALUATION_FAILED",
        message=last_error or "No fue posible evaluar el candidato.",
    )
    return False


def _rank(db: Session, event) -> bool:
    if not event.job_id:
        _fail_event(
            db,
            event,
            code="JOB_UNRESOLVED",
            message="No existe una vacante resuelta para generar ranking.",
        )
        return False

    event.status = "RANKING"
    db.commit()
    for index, delay in enumerate((0,) + RANKING_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            ranking_service.materialize_ranking_from_evaluations(
                db,
                job_id=event.job_id,
                owner_sub=event.owner_sub,
                scope="assigned",
            )
            event.status = "COMPLETED"
            event.completed_at = _now()
            event.last_error_code = None
            event.last_error_message = None
            db.commit()
            return True
        except RankingAlreadyRunning as exc:
            if index < len(RANKING_RETRY_DELAYS):
                continue
            _fail_event(db, event, code="RANKING_FAILED", message=str(exc))
            return False
        except RankingJobNotFound as exc:
            _fail_event(db, event, code="RANKING_FAILED", message=str(exc))
            return False
    return False


def process_ingestion_event(event_id: str) -> str:
    """Resume one provider-neutral ingestion pipeline from its durable status."""
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

            if event.status == "STORED":
                terminal = _prepare_document(db, event)
                if terminal:
                    return terminal
                db.refresh(event)

            if event.status == "INGESTING":
                if not _poll_bedrock(db, event):
                    return event.status
                db.refresh(event)

            if event.status == "EVALUATING":
                if not _evaluate(db, event):
                    return event.status
                db.refresh(event)

            if event.status == "RANKING":
                if not _rank(db, event):
                    return event.status
                db.refresh(event)

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
    """Consume one candidate-ingestion delivery with retry/DLQ semantics."""
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

    if outcome in {"COMPLETED", "FAILED", "NEEDS_REVIEW", "MISSING"}:
        queue.delete_message(message.receipt_handle)
