"""Candidates schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CandidateResponse(BaseModel):
    candidate_id: str
    id: str
    name: str
    email: str | None = None
    created_at: datetime | None = None
    metadata: dict[str, Any] | None = None
    filename: str | None = None

    model_config = {"from_attributes": True}


class CandidateBulkUploadResponse(BaseModel):
    candidate_id: str
    name: str
    original_filename: str
    ingestion_status: str
    ingestion_job_id: str | None = None
    error: str | None = None


class BulkUploadResponse(BaseModel):
    processed: int
    successful: int
    failed: int
    candidates: list[CandidateBulkUploadResponse]
    errors: list[dict[str, str]]


class CandidateEvaluationsResponse(BaseModel):
    evaluations: list[dict[str, Any]]