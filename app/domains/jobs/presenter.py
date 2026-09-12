"""Public response presentation for Jobs."""


def job_payload(job, *, candidate_count: int | None = None) -> dict:
    payload = {
        "job_id": job.id,
        "id": job.id,
        "title": job.title,
        "description": job.description,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }
    if candidate_count is not None:
        payload["candidate_count"] = candidate_count
    return payload


def delete_job_payload(job_id: str, delete_candidates: bool, deleted_candidates: int) -> dict:
    return {
        "detail": (
            "Vacante y candidatos eliminados."
            if delete_candidates
            else "Vacante eliminada."
        ),
        "job_id": job_id,
        "delete_candidates": delete_candidates,
        "deleted_candidates": deleted_candidates if delete_candidates else 0,
    }
