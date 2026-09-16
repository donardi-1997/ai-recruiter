"""Durable shared-queue worker for vacancy candidate reevaluation."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_import_lease_timeout_seconds
from app.db import SessionLocal
from app.domains.candidates import repository as candidates_repository
from app.domains.evaluations import repository as evaluations_repository
from app.domains.evaluations import service as evaluations_service
from app.domains.jobs import reevaluation as reevaluation_repository
from app.domains.jobs import repository as jobs_repository
from app.domains.ranking import service as ranking_service
from app.infrastructure.imports import queue

logger = logging.getLogger(__name__)

MAX_RECEIVE_COUNT = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_message(message: str, fallback: str) -> str:
    value = str(message or "").strip()
    lowered = value.casefold()
    if not value or "http://" in lowered or "https://" in lowered or "x-amz-" in lowered:
        return fallback
    return value[:1000]


def _fail_task(db: Session, task, *, code: str, message: str) -> str:
    task.status = "FAILED"
    task.last_error_code = code
    task.last_error_message = _safe_message(
        message,
        "No fue posible completar la reevaluacion de la vacante.",
    )
    task.completed_at = _now()
    db.commit()
    return task.status


def dispatch_undispatched_job_reevaluations(db: Session) -> int:
    """Repair durable reevaluation tasks committed before SQS dispatch."""
    dispatched = 0
    for task in reevaluation_repository.list_undispatched_reevaluation_tasks(db):
        try:
            queue.send_job_reevaluation(task.id)
        except Exception:
            db.rollback()
            logger.exception("Job reevaluation queue repair failed for task %s", task.id)
            continue
        task.queue_dispatched_at = _now()
        db.commit()
        dispatched += 1
    return dispatched


def process_job_reevaluation(db: Session, *, task_id: str) -> str:
    """Process one durable task using the current vacancy evaluation version.

    The central evaluation service remains the final freshness authority. This
    worker performs a cheap persistence pre-check so already-current candidates
    never enter that service unnecessarily, then calls it with ``force=False``
    for stale/missing/failed evaluations only.
    """
    task = reevaluation_repository.get_reevaluation_task_by_id(db, task_id)
    if task is None:
        return "MISSING"
    if task.status in {"COMPLETED", "FAILED"}:
        return task.status

    job = jobs_repository.get_job(db, task.job_id, owner_sub=task.owner_sub)
    if job is None:
        return _fail_task(
            db,
            task,
            code="JOB_CONTEXT_MISSING",
            message="La vacante ya no esta disponible para este tenant.",
        )

    current_version = int(getattr(job, "evaluation_version", 1) or 1)
    target_version = int(task.target_evaluation_version)
    if current_version > target_version:
        task.status = "COMPLETED"
        task.completed_at = _now()
        task.last_error_code = "SUPERSEDED_BY_NEWER_JOB_VERSION"
        task.last_error_message = (
            "La vacante cambio nuevamente antes de procesar esta reevaluacion."
        )
        db.commit()
        return "SUPERSEDED"
    if current_version < target_version:
        return _fail_task(
            db,
            task,
            code="JOB_VERSION_MISMATCH",
            message="La version solicitada no coincide con la vacante actual.",
        )

    task.status = "PROCESSING"
    task.last_error_code = None
    task.last_error_message = None
    db.commit()

    candidates, _total = candidates_repository.list_candidates_for_job(
        db,
        job.id,
        page=1,
        page_size=100000,
        owner_sub=task.owner_sub,
    )

    failures: list[str] = []
    for candidate in candidates:
        existing = evaluations_repository.get_evaluation_for_job_candidate(
            db,
            job.id,
            candidate.id,
        )
        if not evaluations_repository.needs_evaluation(
            existing,
            current_job_version=current_version,
            force=False,
        ):
            continue

        try:
            evaluation, _newly_evaluated, internal_error = (
                evaluations_service.evaluate_candidate_for_job(
                    db,
                    candidate=candidate,
                    job=job,
                    force=False,
                )
            )
        except Exception as exc:
            logger.exception(
                "Candidate reevaluation failed job=%s candidate=%s",
                job.id,
                candidate.id,
            )
            failures.append(candidate.id)
            continue

        if getattr(evaluation, "status", None) != "COMPLETED" or internal_error:
            failures.append(candidate.id)

        if task.processing_token:
            reevaluation_repository.heartbeat_reevaluation_task(
                db,
                task_id=task.id,
                token=task.processing_token,
            )

    task.status = "RANKING"
    db.commit()
    try:
        ranking_service.materialize_ranking_from_evaluations(
            db,
            job_id=job.id,
            owner_sub=task.owner_sub,
            scope="assigned",
        )
    except Exception as exc:
        return _fail_task(
            db,
            task,
            code="RANKING_FAILED",
            message=str(exc),
        )

    task.status = "COMPLETED"
    task.completed_at = _now()
    if failures:
        task.last_error_code = "PARTIAL_EVALUATION_FAILURES"
        task.last_error_message = (
            f"{len(failures)} candidato(s) no pudieron reevaluarse; "
            "los resultados exitosos se conservaron."
        )
    else:
        task.last_error_code = None
        task.last_error_message = None
    db.commit()
    return task.status


def _process_with_lease(task_id: str) -> str:
    token = str(uuid.uuid4())
    lease_seconds = get_import_lease_timeout_seconds()

    with SessionLocal() as claim_db:
        task = reevaluation_repository.get_reevaluation_task_by_id(claim_db, task_id)
        if task is None:
            return "MISSING"
        if task.status in {"COMPLETED", "FAILED"}:
            return task.status
        if not reevaluation_repository.claim_reevaluation_task(
            claim_db,
            task_id=task.id,
            token=token,
            lease_seconds=lease_seconds,
        ):
            return "BUSY"

    try:
        with SessionLocal() as db:
            return process_job_reevaluation(db, task_id=task_id)
    finally:
        with SessionLocal() as release_db:
            reevaluation_repository.release_reevaluation_task(
                release_db,
                task_id=task_id,
                token=token,
            )


def _mark_retry_exhausted(task_id: str) -> None:
    with SessionLocal() as db:
        task = reevaluation_repository.get_reevaluation_task_by_id(db, task_id)
        if task is None or task.status in {"COMPLETED", "FAILED"}:
            return
        _fail_task(
            db,
            task,
            code="RETRY_EXHAUSTED",
            message="No fue posible completar la reevaluacion tras varios intentos.",
        )


def handle_message(message) -> None:
    """Process one SQS delivery with the shared queue retry/DLQ contract."""
    try:
        outcome = _process_with_lease(message.identifier)
    except Exception:
        logger.exception("Job reevaluation processing failed for task %s", message.identifier)
        if int(message.receive_count) >= MAX_RECEIVE_COUNT:
            _mark_retry_exhausted(message.identifier)
        return

    if outcome in {"MISSING", "COMPLETED", "FAILED", "SUPERSEDED"}:
        queue.delete_message(message.receipt_handle)
