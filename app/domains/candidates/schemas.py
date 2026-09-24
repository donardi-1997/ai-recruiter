"""Candidates schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class CandidateResponse(BaseModel):
    candidate_id: str
    id: str
    name: str
    email: str | None = None
    created_at: datetime | None = None
    metadata: dict[str, Any] | None = None
    filename: str | None = None
    is_banned: bool = False
    banned_at: datetime | None = None
    banned_by_sub: str | None = None
    banned_reason: str | None = None

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


class ApplicationStatusRequest(BaseModel):
    status: str



class CandidateRestrictionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("reason is required")
        return normalized
