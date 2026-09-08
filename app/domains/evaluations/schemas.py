"""Evaluations schemas."""

from pydantic import BaseModel

VALID_RECOMMENDATIONS = {
    "STRONG_MATCH",
    "GOOD_MATCH",
    "PARTIAL_MATCH",
    "LOW_MATCH",
    "EVALUATION_FAILED",
    "PENDING",
}

MIN_SUMMARY_LENGTH = 100


class EvaluateRequest(BaseModel):
    job_id: str


class EvaluationResponse(BaseModel):
    evaluation_id: str
    candidate_id: str
    job_id: str
    status: str
    match_score: float | None = None
    recommendation: str
    summary: str
    strengths: list[str] = []
    gaps: list[str] = []
    requirements: list[dict] = []
    error_message: str | None = None