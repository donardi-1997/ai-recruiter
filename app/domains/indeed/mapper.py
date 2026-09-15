"""Map provider-neutral jobs to Indeed Job Sync inputs."""

from datetime import datetime, timezone

from app.domains.indeed.exceptions import IndeedValidationError


def build_job_input(job, *, careers_base_url: str, source_name: str, company_name: str) -> dict:
    missing = []
    if not (job.title or "").strip():
        missing.append("title")
    if not (job.description or "").strip():
        missing.append("description")
    if not (job.country_code or "").strip():
        missing.append("country_code")
    if not (job.city or "").strip():
        missing.append("city")
    if missing:
        raise IndeedValidationError("Missing Indeed publication fields: " + ", ".join(missing))

    slug = (job.public_slug or str(job.id)).strip("/")
    published = job.published_at or datetime.now(timezone.utc)
    return {
        "jobPostings": [
            {
                "body": {
                    "title": job.title.strip(),
                    "description": job.description.strip(),
                    "descriptionFormatting": "TEXT",
                    "location": {
                        "country": job.country_code.upper(),
                        "cityRegionPostal": job.city.strip(),
                    },
                },
                "metadata": {
                    "jobSource": {
                        "companyName": company_name,
                        "sourceName": source_name,
                        "sourceType": "Employer",
                    },
                    "jobPostingId": str(job.id),
                    "datePublished": published.isoformat(),
                    "url": f"{careers_base_url.rstrip('/')}/{slug}",
                },
            }
        ]
    }
