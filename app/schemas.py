"""Pydantic schemas — JSON responses for the API."""

from datetime import datetime

from pydantic import BaseModel, Field


class CandidateResponse(BaseModel):
    candidate_id: str
    id: str
    name: str
    email: str | None = None
    created_at: datetime | None = None
    metadata: dict | None = None
    filename: str | None = None

    model_config = {"from_attributes": True}


class JobResponse(BaseModel):
    job_id: str
    id: str
    title: str
    description: str | None = None
    created_at: datetime | None = None
    candidate_count: int = 0

    model_config = {"from_attributes": True}


class RankingItemSchema(BaseModel):
    position: int
    candidate_id: str
    score: float
    candidate_name: str = ""
    recommendation: str = ""
    status: str = "COMPLETED"

    model_config = {"from_attributes": True}


class RankingResponse(BaseModel):
    job_id: str
    job_title: str
    page: int = 1
    page_size: int = 10
    total: int = 0
    total_pages: int = 0
    pending_candidates: int = 0
    ranking_generated_at: str | None = None
    ranking_version: int | None = None
    candidates: list[RankingItemSchema] = Field(default_factory=list)


class RecalculateResponse(BaseModel):
    job_id: str
    mode: str
    total_candidates: int
    evaluated: int
    failed: int
    ranking_version: int
