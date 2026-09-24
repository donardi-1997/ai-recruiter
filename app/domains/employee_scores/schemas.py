"""Schemas for private employee scoring."""

from pydantic import BaseModel, Field, field_validator


class CreateScoreEventRequest(BaseModel):
    points: int = Field(ge=-1_000_000, le=1_000_000)
    description: str = Field(min_length=2, max_length=2000)

    @field_validator("points")
    @classmethod
    def reject_zero_points(cls, value: int) -> int:
        if value == 0:
            raise ValueError("points must be non-zero")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("description is required")
        return normalized


class VoidScoreEventRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("reason is required")
        return normalized
