"""Evaluations schemas."""

from pydantic import BaseModel


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