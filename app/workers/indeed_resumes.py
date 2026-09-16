"""Durable worker pipeline for Indeed resume ingestion and AI evaluation."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_import_lease_timeout_seconds
from app.db import SessionLocal
from app.domains.evaluations import service as evaluations_service
from app.domains.indeed import resume_repository
from app.domains.indeed import resumes as resume_download
from app.domains.indeed.resume_models import IndeedResumeIngestion
from app.domains.ranking import service as ranking_service
from app.domains.ranking.exceptions import RankingAlreadyRunning, RankingJobNotFound
from app.infrastructure.imports import ingestion, queue, storage
from app.models import Candidate, IndeedCandidateLink, Job

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


def _sanitize_message(message: str, fallback: str) -> str:
    value = str(message or "").strip()
    if not value:
        return fallback
    lowered = value.lower()
    if "http://" in lowered or "https://" in lowered or "x-amz-" in lowered:
        return fallback
    return value[:1000]


def _fail_task(
    db: Session,
    task: IndeedResumeIngestion,
    *,
    code: str,
    message: str,
) -> None:
    task.status = "FAILED"
    task.last_error_code = code
    task.last_error_message = _sanitize_message(
        message,
        "No fue posible procesar el CV de Indeed.",
    )
    task.completed_at = _now()
    db.commit()


def dispatch_undispatched_resume_ingestions(db: Session) -> int:
    """Repair PENDING resume tasks that were committed but not queued."""
    dispatched = 0
    for task in resume_repository.list_undispatched_resume_ingestions(db):
        try:
            queue.send_indeed_resume_ingestion(task.id)
        except Exception:
            db.rollback()
            logger.exception("Indeed resume queue repair failed for task %s", task.id)
            continue
        task.queue_dispatched_at = _now()
        db.commit()
        dispatched += 1
    return dispatched


def _load_context(db: Session, task: IndeedResumeIngestion):
    link = (
        db.query(IndeedCandidateLink)
        .filter(
            IndeedCandidateLink.id == task.candidate_link_id,
            IndeedCandidateLink.owner_sub == task.owner_sub,
        )
        .first()
    )
    if link is None:
        return None, None, None
    candidate = (
        db.query(Candidate)
        .filter(Candidate.id == link.candidate_id, Candidate.owner_sub == task.owner_sub)
        .first()
    )
    job = (
        db.query(Job)
        .filter(Job.id == link.job_id, Job.owner_sub == task.owner_sub)
        .first()
    )
    return link, candidate, job


def _download_and_store(db: Session, task: IndeedResumeIngestion, link, candidate) -> bool:
    if not link.resume_url:
        _fail_task(
            db,
            task,
            code="RESUME_URL_MISSING",
            message="Indeed no entrego un CV descargable para este candidato.",
        )
        return False

    task.status = "DOWNLOADING"
    task.last_error_code = None
    task.last_error_message = None
    db.commit()

    try:
        downloaded = resume_download.download_resume(link.resume_url, link.resume_name)
    except resume_download.ResumeDownloadError as exc:
        _fail_task(db, task, code=exc.code, message=str(exc))
        return False

    try:
        written = storage.write_canonical_candidate_document(
            candidate_id=candidate.id,
            candidate_name=candidate.name,
            filename=downloaded.filename,
            data=downloaded.data,
            sha256=downloaded.sha256,
        )
    except Exception as exc:
        _fail_task(
            db,
            task,
            code="CANONICAL_STORAGE_FAILED",
            message=str(exc),
        )
        return False

    task.resume_sha256 = downloaded.sha256
    task.canonical_s3_key = written.key
    task.status = "STORED"
    db.commit()
    return True


def _poll_bedrock(db: Session, task: IndeedResumeIngestion) -> bool:
    if not task.resume_sha256:
        _fail_task(
            db,
            task,
            code="CANONICAL_STORAGE_FAILED",
            message="No existe checksum del CV canonico.",
        )
        return False

    task.status = "INGESTING"
    db.commit()

    if not task.bedrock_ingestion_job_id:
        try:
            job_id, _status = ingestion.start_indeed_resume_ingestion(
                task.id,
                task.resume_sha256,
            )
        except Exception as exc:
            _fail_task(
                db,
                task,
                code="BEDROCK_INGESTION_FAILED",
                message=str(exc),
            )
            return False
        task.bedrock_ingestion_job_id = job_id
        db.commit()

    deadline = time.monotonic() + DEFAULT_INGESTION_TIMEOUT_SECONDS
    while True:
        try:
            status = ingestion.get_ingestion_status(task.bedrock_ingestion_job_id)
        except Exception as exc:
            _fail_task(
                db,
                task,
                code="BEDROCK_INGESTION_FAILED",
                message=str(exc),
            )
            return False

        normalized = str(status).upper()
        if normalized == "COMPLETE":
            task.status = "EVALUATING"
            db.commit()
            return True
        if normalized in {"FAILED", "STOPPED"}:
            _fail_task(
                db,
                task,
                code="BEDROCK_INGESTION_FAILED",
                message="La indexacion del CV no pudo completarse.",
            )
            return False
        if time.monotonic() >= deadline:
            _fail_task(
                db,
                task,
                code="BEDROCK_INGESTION_TIMEOUT",
                message="La indexacion del CV excedio el tiempo permitido.",
            )
            return False
        time.sleep(DEFAULT_INGESTION_POLL_SECONDS)


def _is_transient_evaluation_error(message: str | None) -> bool:
    value = str(message or "")
    return any(marker in value for marker in TRANSIENT_EVALUATION_ERRORS)


def _evaluate(db: Session, task: IndeedResumeIngestion, candidate, job) -> bool:
    task.status = "EVALUATING"
    db.commit()

    delays = (0,) + EVALUATION_RETRY_DELAYS
    last_error = None
    for index, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        evaluation, _newly_evaluated, internal_error = (
            evaluations_service.evaluate_candidate_for_owner(
                db,
                candidate_id=candidate.id,
                job_id=job.id,
                owner_sub=task.owner_sub,
            )
        )
        if getattr(evaluation, "status", None) == "COMPLETED" and not internal_error:
            task.status = "RANKING"
            db.commit()
            return True

        last_error = internal_error or getattr(evaluation, "error_message", None)
        if not _is_transient_evaluation_error(last_error) or index == len(delays) - 1:
            break

    _fail_task(
        db,
        task,
        code="EVALUATION_FAILED",
        message=last_error or "No fue posible evaluar el candidato.",
    )
    return False


def _rank(db: Session, task: IndeedResumeIngestion, job) -> bool:
    task.status = "RANKING"
    db.commit()

    for index, delay in enumerate((0,) + RANKING_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            ranking_service.materialize_ranking_from_evaluations(
                db,
                job_id=job.id,
                owner_sub=task.owner_sub,
                scope="assigned",
            )
            task.status = "COMPLETED"
            task.completed_at = _now()
            task.last_error_code = None
            task.last_error_message = None
            db.commit()
            return True
        except RankingAlreadyRunning as exc:
            if index < len(RANKING_RETRY_DELAYS):
                continue
            _fail_task(db, task, code="RANKING_FAILED", message=str(exc))
            return False
        except RankingJobNotFound as exc:
            _fail_task(db, task, code="RANKING_FAILED", message=str(exc))
            return False
        except Exception:
            raise
    return False


def process_resume_ingestion(
    resume_ingestion_id: str,
    *,
    receipt_handle: str | None = None,
) -> str:
    """Resume one Indeed CV pipeline from its latest durable checkpoint."""
    token = str(uuid.uuid4())
    lease_seconds = get_import_lease_timeout_seconds()

    with SessionLocal() as db:
        task = resume_repository.get_resume_ingestion(db, resume_ingestion_id)
        if task is None:
            return "MISSING"
        if task.status in {"COMPLETED", "FAILED"}:
            return task.status
        if not resume_repository.claim_resume_ingestion(
            db,
            ingestion_id=task.id,
            token=token,
            lease_seconds=lease_seconds,
        ):
            return "BUSY"

    try:
        with SessionLocal() as db:
            task = resume_repository.get_resume_ingestion(db, resume_ingestion_id)
            if task is None:
                return "MISSING"
            link, candidate, job = _load_context(db, task)
            if link is None or candidate is None or job is None:
                _fail_task(
                    db,
                    task,
                    code="RESUME_CONTEXT_MISSING",
                    message="El candidato o la vacante ya no estan disponibles.",
                )
                return "FAILED"

            if task.status in {"PENDING", "DOWNLOADING"}:
                if not _download_and_store(db, task, link, candidate):
                    return task.status

            if task.status in {"STORED", "INGESTING"}:
                if not _poll_bedrock(db, task):
                    return task.status

            if task.status == "EVALUATING":
                if not _evaluate(db, task, candidate, job):
                    return task.status

            if task.status == "RANKING":
                if not _rank(db, task, job):
                    return task.status

            return task.status
    finally:
        with SessionLocal() as release_db:
            resume_repository.release_resume_ingestion(
                release_db,
                ingestion_id=resume_ingestion_id,
                token=token,
            )


def _mark_retry_exhausted(resume_ingestion_id: str) -> None:
    with SessionLocal() as db:
        task = resume_repository.get_resume_ingestion(db, resume_ingestion_id)
        if task is None or task.status in {"COMPLETED", "FAILED"}:
            return
        _fail_task(
            db,
            task,
            code="RETRY_EXHAUSTED",
            message="No fue posible completar el procesamiento del CV tras varios intentos.",
        )


def handle_message(message) -> None:
    """Process one Indeed resume SQS delivery with retry/DLQ semantics."""
    try:
        outcome = process_resume_ingestion(
            message.identifier,
            receipt_handle=message.receipt_handle,
        )
    except Exception:
        logger.exception("Indeed resume processing failed for task %s", message.identifier)
        if int(message.receive_count) >= MAX_RECEIVE_COUNT:
            _mark_retry_exhausted(message.identifier)
        return

    if outcome in {"COMPLETED", "FAILED", "MISSING"}:
        queue.delete_message(message.receipt_handle)
