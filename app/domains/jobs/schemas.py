"""Jobs schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EvaluationProfile(BaseModel):
    """Recruiter-reviewed structured criteria used for candidate evaluation."""

    model_config = ConfigDict(extra="forbid")

    required_technologies: list[str] = Field(default_factory=list)
    preferred_technologies: list[str] = Field(default_factory=list)
    required_certifications: list[str] = Field(default_factory=list)
    preferred_certifications: list[str] = Field(default_factory=list)
    minimum_years_experience: float | None = Field(default=None, ge=0)
    specific_experience: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    domain_knowledge: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    technical_competencies: list[str] = Field(default_factory=list)
    assumptions_to_validate: list[str] = Field(default_factory=list)


class JobEnrichmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str | None = None
    country_code: str | None = None
    city: str | None = None
    employment_type: str | None = None
    evaluation_profile: EvaluationProfile | None = None


class JobEnrichmentProposal(EvaluationProfile):
    improved_description: str


class CreateJobRequest(BaseModel):
    title: str
    description: str | None = None
    country_code: str | None = None
    city: str | None = None
    employment_type: str | None = None
    public_slug: str | None = None
    published_at: datetime | None = None
    evaluation_profile: EvaluationProfile | None = None


class UpdateJobRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    country_code: str | None = None
    city: str | None = None
    employment_type: str | None = None
    public_slug: str | None = None
    published_at: datetime | None = None
    evaluation_profile: EvaluationProfile | None = None


class JobResponse(BaseModel):
    job_id: str
    id: str
    title: str
    description: str | None = None
    country_code: str | None = None
    city: str | None = None
    employment_type: str | None = None
    public_slug: str | None = None
    published_at: str | None = None
    created_at: str | None = None
    candidate_count: int = 0
    evaluation_version: int = 1
    evaluation_profile: dict = Field(default_factory=dict)
    evaluation_changed: bool = False
    reevaluation_scheduled: bool = False
    reevaluation_candidate_count: int = 0

    model_config = {"from_attributes": True}


class DeleteJobResponse(BaseModel):
    detail: str
    job_id: str
    delete_candidates: bool
    deleted_candidates: int


class AssignCandidatesRequest(BaseModel):
    candidate_ids: list[str]
