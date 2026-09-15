"""Map provider-neutral jobs to Indeed Job Sync inputs."""

from datetime import datetime, timezone

from app.domains.indeed.exceptions import IndeedValidationError

MIN_TEXT_DESCRIPTION_LENGTH = 30
MAX_TEXT_DESCRIPTION_LENGTH = 20_000
MAX_TITLE_LENGTH = 75


def build_job_input(job, *, careers_base_url: str, source_name: str, company_name: str) -> dict:
    title = (job.title or "").strip()
    description = (job.description or "").strip()
    country_code = (job.country_code or "").strip()
    city = (job.city or "").strip()

    missing = []
    if not title:
        missing.append("title")
    if not description:
        missing.append("description")
    if not country_code:
        missing.append("country_code")
    if not city:
        missing.append("city")
    if missing:
        raise IndeedValidationError("Missing Indeed publication fields: " + ", ".join(missing))

    if len(title) > MAX_TITLE_LENGTH:
        raise IndeedValidationError("Indeed job title must be 75 characters or fewer")
    if not MIN_TEXT_DESCRIPTION_LENGTH <= len(description) <= MAX_TEXT_DESCRIPTION_LENGTH:
        raise IndeedValidationError("Indeed TEXT description must contain between 30 and 20000 characters")
    if len(country_code) != 2 or not country_code.isalpha():
        raise IndeedValidationError("Indeed country_code must be a two-letter ISO country code")

    slug = (job.public_slug or str(job.id)).strip("/")
    published = job.published_at or datetime.now(timezone.utc)
    return {
        "jobPostings": [
            {
                "body": {
                    "title": title,
                    "description": description,
                    "descriptionFormatting": "TEXT",
                    "location": {
                        "country": country_code.upper(),
                        "cityRegionPostal": city,
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
