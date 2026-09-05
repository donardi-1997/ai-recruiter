"""Pydantic schemas for request/response validation."""

from datetime import datetime

from pydantic import BaseModel, Field


# ============================================================
# SHARED
# ============================================================

class Recommendation(str):
    STRONG_MATCH = "STRONG_MATCH"
    GOOD_MATCH   = "GOOD_MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    LOW_MATCH    = "LOW_MATCH"
    PENDING      = "PENDING"


# ============================================================
# JOBS
# ============================================================

class CreateJobRequest(BaseModel):
    title: str = Field(
        ...,
        min_length=3,
        max_length=200,
        description="Título de la vacante",
    )
    description: str = Field(
        ...,
        min_length=10,
        description="Descripción completa de la vacante",
    )


class JobResponse(BaseModel):
    job_id:      str
    owner_id:    str
    title:       str
    description: str
    created_at:  datetime | None = None

    model_config = {"from_attributes": True}


# ============================================================
# CANDIDATES
# ============================================================

class CandidateResponse(BaseModel):
    candidate_id:    str
    owner_id:        str
    name:            str
    filename:        str
    s3_location:     str
    ingestion_status: str | None = None
    indexed:         bool = False
    created_at:      datetime | None = None

    model_config = {"from_attributes": True}


# ============================================================
# JOB ↔ CANDIDATE
# ============================================================

class AssignCandidatesRequest(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list)


class JobCandidateResponse(BaseModel):
    job_id:          str
    candidate_id:    str
    owner_id:        str
    status:          str
    assigned_at:     datetime | None = None

    model_config = {"from_attributes": True}


# ============================================================
# EVALUATIONS
# ============================================================

class RequirementEvaluation(BaseModel):
    requirement: str
    status:      str
    evidence:    str | None = None


class CandidateEvaluationResponse(BaseModel):
    job_id:          str
    candidate_id:    str
    candidate_name:  str
    job_title:       str
    match_score:     int
    recommendation:  str
    requirements:    list[RequirementEvaluation] = Field(default_factory=list)
    strengths:       list[str] = Field(default_factory=list)
    gaps:            list[str] = Field(default_factory=list)
    summary:         str = ""
    evaluated_at:    datetime | None = None

    model_config = {"from_attributes": True}


# ============================================================
# RANKING
# ============================================================

class RankingItemResponse(BaseModel):
    rank:            int
    candidate_id:    str
    candidate_name:  str
    match_score:     int
    recommendation:  str
    strengths:       list[str] = Field(default_factory=list)
    gaps:            list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class RankingMetadataResponse(BaseModel):
    job_id:                 str
    job_title:              str
    ranking_generated_at:   datetime | None = None
    ranking_version:        int | None = None
    total:                  int = 0
    total_pages:            int = 0
    page:                   int = 1
    page_size:              int = 10
    pending_candidates:     int = 0
    candidates:             list[RankingItemResponse] = Field(default_factory=list)


class RecalculateResponse(BaseModel):
    job_id:          str
    mode:            str
    total_candidates: int
    evaluated:       int
    failed:          int
    ranking_version: int
