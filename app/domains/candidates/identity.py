"""Provider-neutral strong identity resolution for candidate documents."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.candidates import repository as candidates_repository
from app.models import Candidate, CandidateIdentity


class CandidateIdentityConflict(RuntimeError):
    """Strong owner-scoped identities resolve to different candidates."""


def normalize_email(value: str | None) -> str | None:
    normalized = str(value or "").strip().casefold()
    return normalized or None


def normalize_phone(value: str | None) -> str | None:
    stripped = str(value or "").strip()
    if not stripped:
        return None
    prefix = "+" if stripped.startswith("+") else ""
    digits = "".join(character for character in stripped if character.isdigit())
    normalized = f"{prefix}{digits}"
    return normalized or None


def _identity_values(parsed_document) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    sha256 = str(getattr(parsed_document, "sha256", "") or "").strip().casefold()
    if sha256:
        values.append(("DOCUMENT_SHA256", sha256))
    email = normalize_email(getattr(parsed_document, "email", None))
    if email:
        values.append(("EMAIL", email))
    phone = normalize_phone(getattr(parsed_document, "phone", None))
    if phone:
        values.append(("PHONE", phone))
    return values


def _find_identity(
    db: Session,
    *,
    owner_sub: str,
    kind: str,
    value: str,
) -> CandidateIdentity | None:
    return (
        db.query(CandidateIdentity)
        .filter(
            CandidateIdentity.owner_sub == owner_sub,
            CandidateIdentity.kind == kind,
            CandidateIdentity.value == value,
        )
        .one_or_none()
    )


def _attach_identity(
    db: Session,
    *,
    owner_sub: str,
    candidate_id: str,
    kind: str,
    value: str,
) -> CandidateIdentity:
    existing = _find_identity(
        db,
        owner_sub=owner_sub,
        kind=kind,
        value=value,
    )
    if existing is not None:
        if existing.candidate_id == candidate_id:
            return existing
        raise CandidateIdentityConflict("IDENTITY_CONFLICT")

    identity = CandidateIdentity(
        owner_sub=owner_sub,
        candidate_id=candidate_id,
        kind=kind,
        value=value,
    )
    try:
        with db.begin_nested():
            db.add(identity)
            db.flush()
        return identity
    except IntegrityError:
        winner = _find_identity(
            db,
            owner_sub=owner_sub,
            kind=kind,
            value=value,
        )
        if winner is not None and winner.candidate_id == candidate_id:
            return winner
        raise CandidateIdentityConflict("IDENTITY_CONFLICT") from None


def _legacy_candidates_by_email(
    db: Session,
    *,
    owner_sub: str,
    normalized_email: str,
) -> list[Candidate]:
    return (
        db.query(Candidate)
        .filter(
            Candidate.owner_sub == owner_sub,
            Candidate.email.isnot(None),
            func.lower(func.trim(Candidate.email)) == normalized_email,
        )
        .order_by(Candidate.created_at.asc(), Candidate.id.asc())
        .all()
    )


def _resolve_matches(matches: dict[str, str]) -> str | None:
    candidate_ids = {candidate_id for candidate_id in matches.values() if candidate_id}
    if len(candidate_ids) > 1:
        raise CandidateIdentityConflict("IDENTITY_CONFLICT")
    return next(iter(candidate_ids), None)


def resolve_or_create_candidate(
    db: Session,
    *,
    owner_sub: str,
    parsed_document,
) -> tuple[Candidate, str]:
    """Resolve strong identities or create a candidate without requiring a job."""
    identity_values = _identity_values(parsed_document)
    matches: dict[str, str] = {}

    for kind, value in identity_values:
        identity = _find_identity(
            db,
            owner_sub=owner_sub,
            kind=kind,
            value=value,
        )
        if identity is not None:
            matches[kind] = identity.candidate_id

    normalized_email = normalize_email(getattr(parsed_document, "email", None))
    if normalized_email:
        legacy = _legacy_candidates_by_email(
            db,
            owner_sub=owner_sub,
            normalized_email=normalized_email,
        )
        if len(legacy) > 1:
            raise CandidateIdentityConflict("IDENTITY_CONFLICT")
        if legacy:
            matches["LEGACY_EMAIL"] = legacy[0].id

    resolved_candidate_id = _resolve_matches(matches)

    try:
        if resolved_candidate_id is None:
            candidate = candidates_repository.create_candidate_pending(
                db,
                name=parsed_document.display_name,
                email=normalized_email,
                metadata={"filename": parsed_document.filename},
                owner_sub=owner_sub,
            )
            outcome = "CREATED"
        else:
            candidate = candidates_repository.get_candidate(
                db,
                resolved_candidate_id,
                owner_sub=owner_sub,
            )
            if candidate is None:
                raise CandidateIdentityConflict("IDENTITY_CONFLICT")
            outcome = "REUSED"

        candidates_repository.update_candidate_document_metadata(
            db,
            candidate,
            filename=parsed_document.filename,
            email=normalized_email,
        )
        for kind, value in identity_values:
            _attach_identity(
                db,
                owner_sub=owner_sub,
                candidate_id=candidate.id,
                kind=kind,
                value=value,
            )

        db.commit()
        db.refresh(candidate)
        return candidate, outcome
    except CandidateIdentityConflict:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
