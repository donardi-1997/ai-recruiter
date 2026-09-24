"""Schemas for the internal training platform."""

from pydantic import BaseModel, Field, field_validator


class CreateCourseRequest(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return value.strip()


class UpdateCourseRequest(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    status: str | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if normalized not in {"DRAFT", "PUBLISHED", "ARCHIVED"}:
            raise ValueError("unsupported course status")
        return normalized


class CreateModuleRequest(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return value.strip()


class CreateLessonRequest(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    video_url: str | None = Field(default=None, max_length=2000)
    duration_seconds: int | None = Field(default=None, ge=1, le=86_400)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return value.strip()

    @field_validator("video_url")
    @classmethod
    def validate_video_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if not normalized.startswith("https://"):
            raise ValueError("video_url must use https")
        return normalized
