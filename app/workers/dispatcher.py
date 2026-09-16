"""Shared SQS worker dispatcher for candidate and vacancy workflows."""

from __future__ import annotations

import logging

from app.db import SessionLocal
from app.infrastructure.imports import queue
from app.infrastructure.imports.queue import ReceivedImportMessage, ReceivedWorkMessage
from app.workers import candidate_imports, candidate_ingestions, indeed_resumes, job_reevaluations

logger = logging.getLogger(__name__)


def repair_undispatched_work() -> int:
    """Repair durable DB work that was committed before its SQS dispatch."""
    with SessionLocal() as db:
        imports = candidate_imports.dispatch_undispatched_batches(db)
        resumes = indeed_resumes.dispatch_undispatched_resume_ingestions(db)
        ingestions = candidate_ingestions.dispatch_undispatched_ingestions(db)
        reevaluations = job_reevaluations.dispatch_undispatched_job_reevaluations(db)
    return imports + resumes + ingestions + reevaluations


def route_message(message: ReceivedWorkMessage) -> None:
    """Send one typed queue message to its owning durable worker."""
    if message.kind == queue.CANDIDATE_IMPORT_KIND:
        candidate_imports.handle_message(
            ReceivedImportMessage(
                batch_id=message.identifier,
                receipt_handle=message.receipt_handle,
                receive_count=message.receive_count,
            )
        )
        return
    if message.kind == queue.INDEED_RESUME_KIND:
        indeed_resumes.handle_message(message)
        return
    if message.kind == queue.CANDIDATE_INGESTION_KIND:
        candidate_ingestions.handle_message(message)
        return
    if message.kind == queue.JOB_REEVALUATION_KIND:
        job_reevaluations.handle_message(message)
        return
    logger.warning("Ignoring unsupported worker message kind: %s", message.kind)


def run_worker_forever() -> None:
    """Continuously repair durable work and consume the shared queue."""
    logger.info("AI Recruiter shared worker started")
    while True:
        try:
            repair_undispatched_work()
        except Exception:
            logger.exception("Shared worker repair cycle failed")

        try:
            messages = queue.receive_work_messages()
        except Exception:
            logger.exception("Shared worker SQS receive failed")
            continue

        for message in messages:
            try:
                route_message(message)
            except Exception:
                logger.exception(
                    "Unhandled shared worker routing failure kind=%s id=%s",
                    message.kind,
                    message.identifier,
                )


def main() -> None:
    run_worker_forever()


if __name__ == "__main__":
    main()
