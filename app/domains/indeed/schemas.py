"""Response schemas for Indeed integration."""

from pydantic import BaseModel


class IndeedIntegrationStatus(BaseModel):
    enabled: bool
    configured: bool
    employer_id_configured: bool


class IndeedJobLinkResponse(BaseModel):
    job_id: str
    sourced_posting_id: str
    employer_job_id: str | None = None
    status: dict | str | None = None
