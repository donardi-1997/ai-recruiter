"""Bedrock Knowledge Base ingestion adapter for candidate documents."""

from __future__ import annotations

import hashlib
import os

from app.config import get_aws_region
from app.infrastructure.bedrock.session import get_cached_session

KNOWLEDGE_BASE_ID = os.getenv("KNOWLEDGE_BASE_ID", "")
DATA_SOURCE_ID = os.getenv("DATA_SOURCE_ID", "")


def _client():
    return get_cached_session().client("bedrock-agent", region_name=get_aws_region())


def _require_ingestion_config() -> tuple[str, str]:
    if not KNOWLEDGE_BASE_ID:
        raise RuntimeError("KNOWLEDGE_BASE_ID is required for Bedrock ingestion")
    if not DATA_SOURCE_ID:
        raise RuntimeError("DATA_SOURCE_ID is required for Bedrock ingestion")
    return KNOWLEDGE_BASE_ID, DATA_SOURCE_ID


def client_token_for_operation(operation_key: str) -> str:
    """Return a deterministic idempotency token for one logical ingestion."""
    return hashlib.sha256(operation_key.encode("utf-8")).hexdigest()


def client_token_for_batch(batch_id: str) -> str:
    """Preserve the existing deterministic token for candidate-import batches."""
    return client_token_for_operation(f"candidate-import:{batch_id}")


def start_ingestion(*, operation_key: str, description: str) -> tuple[str, str]:
    """Start one logical Knowledge Base ingestion with deterministic idempotency."""
    knowledge_base_id, data_source_id = _require_ingestion_config()
    response = _client().start_ingestion_job(
        knowledgeBaseId=knowledge_base_id,
        dataSourceId=data_source_id,
        clientToken=client_token_for_operation(operation_key),
        description=description[:200],
    )
    job = response.get("ingestionJob") or {}
    job_id = job.get("ingestionJobId")
    if not job_id:
        raise RuntimeError("Bedrock ingestion response did not include ingestionJobId")
    return str(job_id), str(job.get("status") or "STARTING")


def start_batch_ingestion(batch_id: str) -> tuple[str, str]:
    """Start the single logical Knowledge Base ingestion job for a batch."""
    operation_key = f"candidate-import:{batch_id}"
    return start_ingestion(
        operation_key=operation_key,
        description=operation_key,
    )


def start_indeed_resume_ingestion(
    resume_ingestion_id: str,
    resume_sha256: str,
) -> tuple[str, str]:
    """Start the deterministic KB ingestion for one canonical Indeed resume."""
    operation_key = f"indeed-resume:{resume_ingestion_id}:{resume_sha256}"
    return start_ingestion(
        operation_key=operation_key,
        description=f"indeed-resume:{resume_ingestion_id}:{resume_sha256[:12]}",
    )


def get_ingestion_status(job_id: str) -> str:
    """Read the real status of an existing Bedrock ingestion job."""
    knowledge_base_id, data_source_id = _require_ingestion_config()
    response = _client().get_ingestion_job(
        knowledgeBaseId=knowledge_base_id,
        dataSourceId=data_source_id,
        ingestionJobId=job_id,
    )
    job = response.get("ingestionJob") or {}
    status = job.get("status")
    if not status:
        raise RuntimeError("Bedrock ingestion response did not include status")
    return str(status)
