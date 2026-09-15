"""Jobs schemas."""

from datetime import datetime

from pydantic import BaseModel


class CreateJobRequest(BaseModel):
    title: str
    description: str | None = None
    country_code: str | None = None
    city: str | None = None
    employment_type: str | None = None
    public_slug: str | None = None
    published_at: datetime | None = None


class UpdateJobRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    country_code: str | None = None
    city: str | None = None
    employment_type: str | None = None
    public_slug: str | None = None
    published_at: datetime | None = None


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

    model_config = {"from_attributes": True}


class DeleteJobResponse(BaseModel):
    detail: str
    job_id: str
    delete_candidates: bool
    deleted_candidates: int


class AssignCandidatesRequest(BaseModel):
    candidate_ids: list[str]
