"""Application services for candidate use cases."""

import os

from sqlalchemy.orm import Session

from app.domains.candidates import repository as candidates_repository
from app.domains.candidates.exceptions import CandidateNotFound, JobNotFound
from app.domains.evaluations import repository as evaluations_repository
from app.domains.jobs import repository as jobs_repository
from app.infrastructure.storage.candidate_documents import index_candidate_document


def require_candidate(
    db: Session,
    candidate_id: str,
    owner_sub: str,
):
    candidate = candidates_repository.get_candidate(
        db,
        candidate_id,
        owner_sub=owner_sub,
    )
    if candidate is None:
        raise CandidateNotFound(candidate_id)
    return candidate


def require_job(
    db: Session,
    job_id: str,
    owner_sub: str,
):
    job = jobs_repository.get_job(db, job_id, owner_sub=owner_sub)
    if job is None:
        raise JobNotFound(job_id)
    return job


def list_candidates(db: Session, owner_sub: str):
    return candidates_repository.list_candidates(db, owner_sub=owner_sub)


def list_job_candidates(
    db: Session,
    job_id: str,
    owner_sub: str,
    *,
    page: int = 1,
    page_size: int = 10,
):
    require_job(db, job_id, owner_sub)
    return candidates_repository.list_candidates_for_job(
        db,
        job_id,
        page=page,
        page_size=page_size,
        owner_sub=owner_sub,
    )


def assign_candidates(
    db: Session,
    job_id: str,
    candidate_ids: list[str],
    owner_sub: str,
):
    require_job(db, job_id, owner_sub)
    return candidates_repository.assign_candidates_to_job(
        db,
        job_id,
        candidate_ids,
        owner_sub=owner_sub,
    )


def get_job_candidate_evaluation(
    db: Session,
    job_id: str,
    candidate_id: str,
    owner_sub: str,
):
    require_job(db, job_id, owner_sub)
    require_candidate(db, candidate_id, owner_sub)
    return evaluations_repository.get_evaluation_for_job_candidate(
        db,
        job_id,
        candidate_id,
    )


def get_candidate_evaluations(
    db: Session,
    candidate_id: str,
    owner_sub: str,
):
    require_candidate(db, candidate_id, owner_sub)
    return evaluations_repository.get_evaluations_for_candidate(db, candidate_id)


def delete_candidate(
    db: Session,
    candidate_id: str,
    owner_sub: str,
) -> bool:
    require_candidate(db, candidate_id, owner_sub)
    return candidates_repository.delete_candidate(db, candidate_id)


def delete_all_candidates(db: Session, owner_sub: str) -> tuple[int, int]:
    return candidates_repository.delete_all_candidates(db, owner_sub=owner_sub)


def create_and_index_candidate(
    db: Session,
    *,
    owner_sub: str,
    original_filename: str | None,
    file_content: bytes,
):
    name = os.path.splitext(original_filename or "Unknown")[0]
    candidate = candidates_repository.create_candidate(
        db,
        name=name,
        metadata={"filename": original_filename},
        owner_sub=owner_sub,
    )
    indexing = index_candidate_document(
        candidate,
        file_content,
        original_filename,
    )
    return candidate, indexing


__all__ = [
    "CandidateNotFound",
    "JobNotFound",
    "require_candidate",
    "require_job",
    "list_candidates",
    "list_job_candidates",
    "assign_candidates",
    "get_job_candidate_evaluation",
    "get_candidate_evaluations",
    "delete_candidate",
    "delete_all_candidates",
    "create_and_index_candidate",
]
