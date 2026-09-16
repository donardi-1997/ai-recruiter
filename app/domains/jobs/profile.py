"""Canonical vacancy evaluation-profile normalization and comparison."""

from __future__ import annotations

from typing import Any


PROFILE_LIST_FIELDS = (
    "required_technologies",
    "preferred_technologies",
    "required_certifications",
    "preferred_certifications",
    "specific_experience",
    "responsibilities",
    "domain_knowledge",
    "education",
    "languages",
    "technical_competencies",
    "assumptions_to_validate",
)


def normalize_text(value: Any) -> str:
    """Collapse whitespace without changing recruiter-authored word order."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def normalize_evaluation_profile(profile: dict | None) -> dict:
    """Return the stable profile shape used for persistence and equality checks."""
    raw = dict(profile or {})
    normalized: dict[str, Any] = {}

    for field in PROFILE_LIST_FIELDS:
        values = raw.get(field) or []
        if not isinstance(values, (list, tuple)):
            values = [values]
        cleaned = []
        for value in values:
            item = normalize_text(value)
            if item:
                cleaned.append(item)
        normalized[field] = cleaned

    years = raw.get("minimum_years_experience")
    if years in (None, ""):
        normalized["minimum_years_experience"] = None
    else:
        number = float(years)
        normalized["minimum_years_experience"] = int(number) if number.is_integer() else number

    return normalized


def evaluation_signature(
    title: str | None,
    description: str | None,
    profile: dict | None,
) -> tuple:
    """Build a deterministic equality signature for evaluation-relevant content."""
    normalized_profile = normalize_evaluation_profile(profile)
    profile_signature = tuple(
        (
            key,
            tuple(value) if isinstance(value, list) else value,
        )
        for key, value in normalized_profile.items()
    )
    return (
        normalize_text(title),
        normalize_text(description),
        profile_signature,
    )
