"""Bedrock Knowledge Base ingestion adapter for candidate-import batches."""

from __future__ import annotations

import hashlib
import os

from app.config import get_aws_region
from app.infrastructure.bedrock.session import get_cached_session

KNOWLEDGE_BASE_ID = os.getenv("KNOWLEDGE_BASE_ID", "VUGNMJQAEN")
DATA_SOURCE_ID = os.getenv("DATA_SOURCE_ID", "P8SUL2VFHA")


def _client():
    return get_cached_session().client("bedrock-agent", region_name=get_aws_region())


def client_token_for_batch(batch_id: str) -> str:
    """Return a deterministic idempotency token for one logical batch ingestion."""
    return hashlib.sha256(
        f"candidate-import:{batch_id}".encode("utf-8")
    ).hexdigest()


def start_batch_ingestion(batch_id: str) -> tuple[str, str]:
    """Start the single logical Knowledge Base ingestion job for a batch."""
    response = _client().start_ingestion_job(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        dataSourceId=DATA_SOURCE_ID,
        clientToken=client_token_for_batch(batch_id),
        description=f"candidate-import:{batch_id}"[:200],
    )
    job = response.get("ingestionJob") or {}
    job_id = job.get("ingestionJobId")
    if not job_id:
        raise RuntimeError("Bedrock ingestion response did not include ingestionJobId")
    return str(job_id), str(job.get("status") or "STARTING")


def get_ingestion_status(job_id: str) -> str:
    """Read the real status of an existing Bedrock ingestion job."""
    response = _client().get_ingestion_job(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        dataSourceId=DATA_SOURCE_ID,
        ingestionJobId=job_id,
    )
    job = response.get("ingestionJob") or {}
    status = job.get("status")
    if not status:
        raise RuntimeError("Bedrock ingestion response did not include status")
    return str(status)
