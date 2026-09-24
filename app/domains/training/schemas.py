"""Schemas for the internal training platform."""

from pydantic import BaseModel, Field, field_validator, model_validator


class CreateCourseRequest(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    is_onboarding: bool = False

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return value.strip()


class UpdateCourseRequest(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    is_onboarding: bool | None = None
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
    audience_job_title: str | None = Field(default=None, max_length=200)
    audience_department: str | None = Field(default=None, max_length=200)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return value.strip()

    @field_validator("audience_job_title", "audience_department")
    @classmethod
    def normalize_optional_scope(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CreateLessonRequest(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    video_url: str | None = Field(default=None, max_length=2000)
    duration_seconds: int | None = Field(default=None, ge=1, le=86_400)
    content_type: str = "VIDEO"
    external_url: str | None = Field(default=None, max_length=2000)
    estimated_minutes: int | None = Field(default=None, ge=1, le=1440)
    checklist_items: list[str] = Field(default_factory=list, max_length=20)
    is_optional: bool = False

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return value.strip()

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"VIDEO", "ARTICLE", "RESOURCE", "CHECKLIST"}:
            raise ValueError("unsupported lesson content_type")
        return normalized

    @field_validator("checklist_items")
    @classmethod
    def normalize_checklist_items(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip() for item in value if str(item).strip()]
        if len(set(normalized)) != len(normalized):
            raise ValueError("checklist items must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_checklist_content(self):
        if self.checklist_items and self.content_type != "CHECKLIST":
            raise ValueError("checklist_items require CHECKLIST content_type")
        return self

    @field_validator("video_url", "external_url")
    @classmethod
    def validate_video_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if not normalized.startswith("https://"):
            raise ValueError("URL must use https")
        return normalized



class CreateQuizRequest(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    passing_score: int = Field(default=70, ge=1, le=100)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return value.strip()


class CreateQuizQuestionRequest(BaseModel):
    prompt: str = Field(min_length=2, max_length=2000)
    options: list[str] = Field(min_length=2, max_length=6)
    correct_option: int = Field(ge=0)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        return value.strip()

    @field_validator("options")
    @classmethod
    def normalize_options(cls, value: list[str]) -> list[str]:
        normalized = [str(option).strip() for option in value]
        if any(not option for option in normalized):
            raise ValueError("quiz options cannot be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("quiz options must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_correct_option(self):
        if self.correct_option >= len(self.options):
            raise ValueError("correct_option is outside the option range")
        return self


class UpdateChecklistProgressRequest(BaseModel):
    completed_items: list[int] = Field(default_factory=list, max_length=20)

    @field_validator("completed_items")
    @classmethod
    def normalize_completed_items(cls, value: list[int]) -> list[int]:
        if any(index < 0 for index in value):
            raise ValueError("completed_items cannot contain negative indexes")
        return sorted(set(value))


class SubmitQuizAttemptRequest(BaseModel):
    answers: dict[str, int]



class CreateLessonVideoUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(ge=1, le=1_073_741_824)

    @field_validator("filename", "content_type")
    @classmethod
    def normalize_video_manifest_text(cls, value: str) -> str:
        return value.strip()


class FinalizeLessonVideoUploadRequest(BaseModel):
    key: str = Field(min_length=1, max_length=2000)
    content_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(ge=1, le=1_073_741_824)

    @field_validator("key", "content_type")
    @classmethod
    def normalize_video_finalize_text(cls, value: str) -> str:
        return value.strip()
