"""Stable environment-derived application configuration."""

import os
from dataclasses import dataclass

DEFAULT_AWS_REGION = "us-east-2"

CORS_ORIGINS = (
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "https://ai.adrianguerra.net",
    "https://air.adrianguerra.net",
)


@dataclass(frozen=True)
class IndeedSettings:
    enabled: bool
    client_id: str
    client_secret: str
    employer_id: str
    scope: str
    source_name: str
    company_name: str
    token_url: str
    graphql_url: str
    request_timeout_seconds: float
    careers_base_url: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.source_name and self.company_name)


def get_aws_region() -> str:
    """Return the configured AWS region without caching environment state."""
    return os.getenv("AWS_REGION", DEFAULT_AWS_REGION)


def get_database_url() -> str:
    """Return DATABASE_URL using the existing empty-string default."""
    return os.getenv("DATABASE_URL", "")


def get_import_staging_bucket() -> str:
    """Return the dedicated private bucket used for temporary import uploads."""
    return os.environ["IMPORT_STAGING_BUCKET"]


def get_import_queue_url() -> str:
    """Return the SQS queue URL used by the candidate-import worker."""
    return os.environ["IMPORT_QUEUE_URL"]


def get_import_evaluation_concurrency() -> int:
    """Return the bounded number of candidate evaluations run concurrently."""
    return int(os.getenv("IMPORT_EVALUATION_CONCURRENCY", "3"))


def get_import_lease_timeout_seconds() -> int:
    """Return the stale-worker lease timeout used for crash recovery."""
    return int(os.getenv("IMPORT_LEASE_TIMEOUT_SECONDS", "300"))


def get_indeed_settings() -> IndeedSettings:
    """Return Indeed integration settings without caching secret environment state."""
    return IndeedSettings(
        enabled=os.getenv("INDEED_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
        client_id=os.getenv("INDEED_CLIENT_ID", "").strip(),
        client_secret=os.getenv("INDEED_CLIENT_SECRET", "").strip(),
        employer_id=os.getenv("INDEED_EMPLOYER_ID", "").strip(),
        scope=os.getenv("INDEED_SCOPE", "employer_access employer.hosted_job").strip(),
        source_name=os.getenv("INDEED_SOURCE_NAME", "").strip(),
        company_name=os.getenv("INDEED_COMPANY_NAME", "").strip(),
        token_url=os.getenv("INDEED_TOKEN_URL", "https://apis.indeed.com/oauth/v2/tokens").strip(),
        graphql_url=os.getenv("INDEED_GRAPHQL_URL", "https://apis.indeed.com/graphql").strip(),
        request_timeout_seconds=float(os.getenv("INDEED_REQUEST_TIMEOUT_SECONDS", "10")),
        careers_base_url=os.getenv("CAREERS_BASE_URL", "https://www.asiaticorp.com/jobs").rstrip("/"),
    )
