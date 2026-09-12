"""Evaluations schemas."""

from pydantic import BaseModel

from app.domains.evaluations.rules import VALID_RECOMMENDATIONS, MIN_SUMMARY_LENGTH


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

# Re-export for backward compatibility
__all__ = [
    "EvaluateRequest",
    "EvaluationResponse",
    "VALID_RECOMMENDATIONS",
    "MIN_SUMMARY_LENGTH",
]