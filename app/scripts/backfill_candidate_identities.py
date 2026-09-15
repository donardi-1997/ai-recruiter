"""Backfill strong identities for candidates created before import V1."""

from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.domains.candidate_imports import repository
from app.domains.candidate_imports.exceptions import IdentityConflict
from app.domains.candidate_imports.rules import document_sha256, normalize_email
from app.infrastructure.imports import storage
from app.models import Candidate

logger = logging.getLogger(__name__)


def read_existing_canonical_document(candidate_id: str) -> bytes | None:
    """Read an existing canonical PDF/DOCX when one is available."""
    return storage.read_existing_canonical_document(candidate_id)


def _attach_if_missing(
    db: Session,
    *,
    owner_sub: str,
    candidate_id: str,
    kind: str,
    value: str,
) -> bool:
    """Attach one identity and report whether this run created it."""
    existing = repository.find_identity(
        db,
        owner_sub=owner_sub,
        kind=kind,
        value=value,
    )
    if existing is not None:
        if existing.candidate_id != candidate_id:
            raise IdentityConflict("IDENTITY_CONFLICT")
        return False

    repository.attach_identity(
        db,
        owner_sub=owner_sub,
        candidate_id=candidate_id,
        kind=kind,
        value=value,
    )
    return True


def backfill_candidate_identities(db: Session) -> dict[str, int]:
    """Seed safe owner-scoped email and document-hash identities idempotently."""
    candidates = db.query(Candidate).order_by(Candidate.owner_sub, Candidate.id).all()
    owned_candidates = [candidate for candidate in candidates if candidate.owner_sub]

    result = {
        "candidates_scanned": len(candidates),
        "skipped_ownerless": len(candidates) - len(owned_candidates),
        "email_identities_seeded": 0,
        "document_identities_seeded": 0,
        "email_conflicts": 0,
        "identity_conflicts": 0,
        "documents_missing": 0,
    }

    email_groups: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
    for candidate in owned_candidates:
        if not candidate.email:
            continue
        normalized_email = normalize_email(candidate.email)
        if normalized_email:
            email_groups[(candidate.owner_sub, normalized_email)].append(candidate)

    for (owner_sub, normalized_email), grouped_candidates in email_groups.items():
        if len(grouped_candidates) != 1:
            result["email_conflicts"] += 1
            logger.warning(
                "Skipping ambiguous legacy email identity for owner candidate_ids=%s",
                [candidate.id for candidate in grouped_candidates],
            )
            continue

        candidate = grouped_candidates[0]
        try:
            if _attach_if_missing(
                db,
                owner_sub=owner_sub,
                candidate_id=candidate.id,
                kind="EMAIL",
                value=normalized_email,
            ):
                result["email_identities_seeded"] += 1
        except IdentityConflict:
            result["identity_conflicts"] += 1
            logger.warning(
                "Candidate identity conflict during legacy backfill candidate_id=%s kind=EMAIL",
                candidate.id,
            )

    for candidate in owned_candidates:
        document = read_existing_canonical_document(candidate.id)
        if document is None:
            result["documents_missing"] += 1
            continue

        digest = document_sha256(document)
        try:
            if _attach_if_missing(
                db,
                owner_sub=candidate.owner_sub,
                candidate_id=candidate.id,
                kind="DOCUMENT_SHA256",
                value=digest,
            ):
                result["document_identities_seeded"] += 1
        except IdentityConflict:
            result["identity_conflicts"] += 1
            logger.warning(
                "Candidate identity conflict during legacy backfill candidate_id=%s kind=DOCUMENT_SHA256",
                candidate.id,
            )

    db.commit()
    return result


def main() -> None:
    """Run the backfill against the configured application database."""
    with SessionLocal() as db:
        result = backfill_candidate_identities(db)
    logger.info("Candidate identity backfill complete: %s", result)


if __name__ == "__main__":
    main()
