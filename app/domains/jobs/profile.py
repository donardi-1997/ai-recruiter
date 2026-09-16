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


def _list_section(label: str, values: list[str], *, preferred: bool = False) -> str | None:
    if not values:
        return None
    suffix = " — deseables, no obligatorios" if preferred else ""
    items = "\n".join(f"- {value}" for value in values)
    return f"{label}{suffix}:\n{items}"


def build_evaluation_text(job) -> str:
    """Build the vacancy text consumed by retrieval and candidate evaluation.

    Recruiter-approved structured criteria are appended to the authored job
    description. Preferred technologies/certifications are explicitly marked as
    non-mandatory and unresolved assumptions are intentionally excluded so they
    cannot silently become candidate filters.
    """
    profile = normalize_evaluation_profile(getattr(job, "evaluation_profile", None))
    base = normalize_text(getattr(job, "description", None)) or normalize_text(
        getattr(job, "title", None)
    )

    sections: list[str] = []
    for label, field, preferred in (
        ("Tecnologías requeridas", "required_technologies", False),
        ("Tecnologías preferidas", "preferred_technologies", True),
        ("Certificaciones requeridas", "required_certifications", False),
        ("Certificaciones preferidas", "preferred_certifications", True),
        ("Experiencia específica", "specific_experience", False),
        ("Responsabilidades", "responsibilities", False),
        ("Conocimiento de dominio", "domain_knowledge", False),
        ("Educación", "education", False),
        ("Idiomas", "languages", False),
        ("Competencias técnicas", "technical_competencies", False),
    ):
        section = _list_section(label, profile[field], preferred=preferred)
        if section:
            sections.append(section)

    years = profile.get("minimum_years_experience")
    if years is not None:
        sections.append(f"Experiencia mínima: {years} años.")

    if not sections:
        return base

    return "\n\n".join(
        [
            base,
            "CRITERIOS ESTRUCTURADOS APROBADOS POR RR. HH.",
            *sections,
        ]
    ).strip()
