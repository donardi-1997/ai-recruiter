"""HTTP-facing request schemas for candidate imports."""

from pydantic import BaseModel, Field


class ImportUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    size_bytes: int = Field(gt=0)
    content_type: str = Field(min_length=1, max_length=255)


class CreateImportBatchRequest(BaseModel):
    job_id: str = Field(min_length=1)
    uploads: list[ImportUploadRequest] = Field(min_length=1)
