"""Schemas for employee administration."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


RoleCode = Literal["SUPER_ADMIN", "ADMIN", "EMPLOYEE"]
EmployeeStatus = Literal["ACTIVE", "DISABLED"]


class CreateEmployeeRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    job_title: str | None = Field(default=None, max_length=160)
    department: str | None = Field(default=None, max_length=160)
    hire_date: date | None = None
    role: RoleCode = "EMPLOYEE"
    assign_onboarding: bool = True

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized.count("@") != 1:
            raise ValueError("invalid email")
        local, domain = normalized.split("@", 1)
        if not local or not domain or "." not in domain:
            raise ValueError("invalid email")
        return normalized

    @field_validator("first_name", "last_name")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("job_title", "department")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class UpdateEmployeeRequest(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    job_title: str | None = Field(default=None, max_length=160)
    department: str | None = Field(default=None, max_length=160)
    hire_date: date | None = None

    @field_validator("first_name", "last_name", "job_title", "department")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SetEmployeeRoleRequest(BaseModel):
    role: RoleCode


class SetEmployeeStatusRequest(BaseModel):
    status: EmployeeStatus
