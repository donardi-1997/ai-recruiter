"""Public response presentation for Jobs."""


def job_payload(job, *, candidate_count: int | None = None) -> dict:
    payload = {
        "job_id": job.id,
        "id": job.id,
        "title": job.title,
        "description": job.description,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }

    optional_fields = {
        "country_code": getattr(job, "country_code", None),
        "city": getattr(job, "city", None),
        "employment_type": getattr(job, "employment_type", None),
        "public_slug": getattr(job, "public_slug", None),
    }
    for key, value in optional_fields.items():
        if value is not None:
            payload[key] = value

    published_at = getattr(job, "published_at", None)
    if published_at is not None:
        payload["published_at"] = published_at.isoformat()

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
