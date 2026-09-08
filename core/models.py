from pydantic import BaseModel, Field


# ============================================================
# AUTH MODELS
# ============================================================


class LoginRequest(BaseModel):
    email: str
    password: str


# ============================================================
# CANDIDATE MODELS
# ============================================================


class AskCandidateRequest(BaseModel):
    question: str = Field(
        ..., min_length=1, description="Pregunta sobre el candidato"
    )


class Source(BaseModel):
    file: str | None = None
    score: float
    page: int | None = None


class AskCandidateResponse(BaseModel):
    candidate_id: str
    answer: str
    sources: list[Source]


class EvaluateCandidateRequest(BaseModel):
    job_description: str = Field(
        ..., min_length=10, description="Descripción de la vacante"
    )


class RequirementEvaluation(BaseModel):
    requirement: str
    status: str
    evidence: str | None = None


class CandidateEvaluation(BaseModel):
    candidate_id: str
    match_score: int
    recommendation: str
    requirements: list[RequirementEvaluation] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    summary: str
    sources: list[Source] = Field(default_factory=list)


# ============================================================
# JOB MODELS
# ============================================================


class CreateJobRequest(BaseModel):
    title: str = Field(..., min_length=3, description="Título de la vacante")
    description: str = Field(
        ..., min_length=10, description="Descripción completa de la vacante"
    )


class EvaluateJobRequest(BaseModel):
    job_id: str


class AssignCandidatesRequest(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list)


class JobResponse(BaseModel):
    job_id: str
    title: str
    description: str


# ============================================================
# RANKING MODELS
# ============================================================


class CandidateRankingItem(BaseModel):
    rank: int
    candidate_id: str
    candidate_name: str
    match_score: int | None = None
    recommendation: str
    status: str
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class JobRankingResponse(BaseModel):
    job_id: str
    job_title: str
    page: int
    page_size: int
    total: int
    total_pages: int
    pending_candidates: int = 0
    ranking_generated_at: str | None = None
    ranking_version: int | None = None
    candidates: list[CandidateRankingItem]


class CandidateJobEvaluationResponse(BaseModel):
    job_id: str
    candidate_id: str
    candidate_name: str
    candidate_filename: str
    match_score: int
    recommendation: str
    requirements: list
    strengths: list[str]
    gaps: list[str]
    summary: str


# ============================================================
# JOB SUMMARY MODELS
# ============================================================


class JobSummaryTopCandidate(BaseModel):
    candidate_id: str
    candidate_name: str
    match_score: int
    recommendation: str


class JobSummaryResponse(BaseModel):
    job_id: str
    job_title: str
    total_candidates: int
    evaluated_candidates: int
    pending_candidates: int
    failed_candidates: int
    strong_matches: int
    partial_matches: int
    low_matches: int
    average_score: float
    top_candidate: JobSummaryTopCandidate | None


# ============================================================
# COMPARISON MODELS
# ============================================================


class CandidateComparisonItem(BaseModel):
    candidate_id: str
    candidate_name: str
    match_score: int
    recommendation: str
    strengths: list[str]
    gaps: list[str]


class CandidateComparisonResponse(BaseModel):
    job_id: str
    job_title: str
    candidates: list[CandidateComparisonItem]
    winner: CandidateComparisonItem | None


# ============================================================
# REQUIREMENTS MODELS
# ============================================================


class CandidateRequirementItem(BaseModel):
    requirement: str
    status: str
    evidence: str | None = None


class CandidateRequirementsResponse(BaseModel):
    job_id: str
    job_title: str
    candidate_id: str
    candidate_name: str
    match_score: int
    recommendation: str
    requirements: list[CandidateRequirementItem]
