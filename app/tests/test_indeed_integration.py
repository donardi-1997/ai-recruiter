"""Contract tests for the Indeed Employers integration."""

from app.models import Job


def test_job_exposes_neutral_publication_fields():
    """Jobs must carry provider-neutral publication metadata before syncing externally."""
    for field in (
        "country_code",
        "city",
        "employment_type",
        "public_slug",
        "published_at",
    ):
        assert hasattr(Job, field), f"Job is missing neutral publication field: {field}"
