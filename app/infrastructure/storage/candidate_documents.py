"""Candidate document indexing infrastructure."""

import json
import logging
import os

from app.evaluation import _bedrock_session

logger = logging.getLogger(__name__)

S3_BUCKET = os.getenv("S3_BUCKET", "ai-cv-rag-adrian-2026")
S3_PREFIX = "documents"
KNOWLEDGE_BASE_ID = os.getenv("KNOWLEDGE_BASE_ID", "VUGNMJQAEN")
DATA_SOURCE_ID = os.getenv("DATA_SOURCE_ID", "P8SUL2VFHA")


def _get_bedrock_s3_clients():
    """Get S3 and Bedrock Agent clients using the configured session."""
    s3 = _bedrock_session.client("s3", region_name=os.getenv("AWS_REGION", "us-east-2"))
    bedrock_agent = _bedrock_session.client("bedrock-agent", region_name=os.getenv("AWS_REGION", "us-east-2"))
    return s3, bedrock_agent


def index_candidate_document(candidate, file_content: bytes, filename: str) -> dict:
    """Upload CV to S3 with PostgreSQL candidate.id and trigger KB ingestion.

    This is the single source of truth for candidate document indexing.
    Uses candidate.id (PostgreSQL UUID) as the canonical candidate_id.

    Returns dict with ingestion_status and optional error.
    """
    candidate_id = str(candidate.id)
    s3_key = f"{S3_PREFIX}/cv-{candidate_id}.pdf"
    metadata_key = f"{S3_PREFIX}/cv-{candidate_id}.pdf.metadata.json"

    s3, bedrock_agent = _get_bedrock_s3_clients()

    # 1. Upload CV PDF to S3
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=file_content,
            ContentType="application/pdf",
        )
        logger.info("S3 upload OK: %s", s3_key)
    except Exception as exc:
        logger.error("S3 upload failed for candidate %s: %s", candidate_id, exc)
        return {"status": "UPLOAD_FAILED", "error": str(exc)}

    # 2. Create and upload metadata with canonical candidate_id
    metadata = {
        "metadataAttributes": {
            "candidate_id": {"value": {"type": "STRING", "stringValue": candidate_id}},
            "candidate_name": {"value": {"type": "STRING", "stringValue": candidate.name}},
        }
    }
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=metadata_key,
            Body=json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("S3 metadata OK: %s", metadata_key)
    except Exception as exc:
        logger.error("S3 metadata failed for candidate %s: %s", candidate_id, exc)
        return {"status": "METADATA_FAILED", "error": str(exc)}

    # 3. Trigger Knowledge Base ingestion
    try:
        response = bedrock_agent.start_ingestion_job(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            dataSourceId=DATA_SOURCE_ID,
        )
        job = response.get("ingestionJob", {})
        ingestion_status = job.get("status") or "STARTING"
        ingestion_job_id = job.get("ingestionJobId")
        logger.info(
            "KB ingestion started: job_id=%s status=%s candidate=%s",
            ingestion_job_id, ingestion_status, candidate_id,
        )
        return {
            "status": ingestion_status,
            "ingestion_job_id": ingestion_job_id,
        }
    except Exception as exc:
        logger.error("KB ingestion failed for candidate %s: %s", candidate_id, exc)
        return {"status": "INGESTION_FAILED", "error": str(exc)}