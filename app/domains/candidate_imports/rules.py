"""Deterministic rules for candidate-import identity and state changes."""

import hashlib

from app.domains.candidate_imports.exceptions import IdentityConflict


TERMINAL_BATCH_STATUSES = {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"}

ALLOWED_STAGE_NEXT = {
    "UPLOADING": {"VALIDATING"},
    "VALIDATING": {"DEDUPLICATING"},
    "DEDUPLICATING": {"INGESTING", "EVALUATING"},
    "INGESTING": {"EVALUATING"},
    "EVALUATING": {"RANKING"},
    "RANKING": {"COMPLETED"},
    "COMPLETED": set(),
}


class InvalidTransition(Exception):
    """The requested batch state transition is not allowed."""


def normalize_email(value: str) -> str:
    """Normalize an email for owner-scoped identity matching."""
    return value.strip().casefold()


def normalize_phone(value: str) -> str:
    """Normalize a phone while preserving an explicit leading plus sign."""
    stripped = value.strip()
    prefix = "+" if stripped.startswith("+") else ""
    digits = "".join(character for character in stripped if character.isdigit())
    return f"{prefix}{digits}"


def document_sha256(data: bytes) -> str:
    """Return the stable SHA-256 identity for document bytes."""
    return hashlib.sha256(data).hexdigest()


def resolve_identity_candidates(matches: dict[str, str]) -> str | None:
    """Resolve strong identity matches without ever guessing between people."""
    candidate_ids = {candidate_id for candidate_id in matches.values() if candidate_id}
    if len(candidate_ids) > 1:
        raise IdentityConflict("IDENTITY_CONFLICT")
    return next(iter(candidate_ids), None)


def transition_batch(
    status: str,
    current_stage: str,
    next_stage: str,
) -> tuple[str, str]:
    """Validate a forward batch transition and derive its public status."""
    if status in TERMINAL_BATCH_STATUSES:
        raise InvalidTransition(
            f"Cannot transition terminal batch from {status}/{current_stage} to {next_stage}"
        )

    allowed = ALLOWED_STAGE_NEXT.get(current_stage, set())
    if next_stage not in allowed:
        raise InvalidTransition(
            f"Invalid candidate import transition: {current_stage} -> {next_stage}"
        )

    next_status = "COMPLETED" if next_stage == "COMPLETED" else "PROCESSING"
    return next_status, next_stage
