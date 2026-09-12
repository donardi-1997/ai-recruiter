"""Ranking schemas."""

from typing import Any

from pydantic import BaseModel


class RankingItemSchema(BaseModel):
    position: int
    candidate_id: str
    match_score: float
    candidate_name: str = ""
    recommendation: str = ""
    status: str = "COMPLETED"
    strengths: list[str] = []
    gaps: list[str] = []

    model_config = {"from_attributes": True}


class RankingResponse(BaseModel):
    job_id: str
    job_title: str
    ranking_generated_at: str | None = None
    ranking_version: int | None = None
    ranking_scope: str = "assigned"
    scope_mismatch: bool = False
    ranking_total: int = 0
    total: int = 0
    total_pages: int = 0
    page: int = 1
    page_size: int = 10
    pending_candidates: int = 0
    score_min: float | None = None
    score_max: float | None = None
    candidates: list[RankingItemSchema] = []


class RecalculateRequest(BaseModel):
    mode: str = "full"
    scope: str = "assigned"


class RecalculateResponse(BaseModel):
    job_id: str
    mode: str
    scope: str
    total_candidates: int
    evaluated: int
    failed: int
    failures: list[dict[str, Any]] = []
    ranking_version: int


class LatestRankingResponse(BaseModel):
    job_id: str
    job_title: str
    ranking_generated_at: str | None = None
    ranking_version: int
    total: int
    total_pages: int
    page: int
    page_size: int
    pending_candidates: int
    candidates: list[dict[str, Any]]