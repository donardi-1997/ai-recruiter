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


@dataclass(frozen=True)
class GmailSettings:
    """OAuth-backed Gmail transport settings loaded exclusively from environment."""

    enabled: bool
    client_id: str
    client_secret: str
    refresh_token: str
    user_id: str
    query: str
    allowed_senders: tuple[str, ...]
    scope: str
    token_url: str
    api_base_url: str
    request_timeout_seconds: float

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)


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


def get_gmail_settings() -> GmailSettings:
    """Return swappable Gmail OAuth settings without ever reading a mailbox password."""
    allowed_senders = tuple(
        value.strip().casefold()
        for value in os.getenv("GMAIL_ALLOWED_SENDERS", "").split(",")
        if value.strip()
    )
    return GmailSettings(
        enabled=os.getenv("GMAIL_ENABLED", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        client_id=os.getenv("GMAIL_CLIENT_ID", "").strip(),
        client_secret=os.getenv("GMAIL_CLIENT_SECRET", "").strip(),
        refresh_token=os.getenv("GMAIL_REFRESH_TOKEN", "").strip(),
        user_id=os.getenv("GMAIL_USER_ID", "me").strip() or "me",
        query=os.getenv("GMAIL_QUERY", "has:attachment").strip(),
        allowed_senders=allowed_senders,
        scope=os.getenv(
            "GMAIL_SCOPE",
            "https://www.googleapis.com/auth/gmail.readonly",
        ).strip(),
        token_url=os.getenv(
            "GMAIL_TOKEN_URL",
            "https://oauth2.googleapis.com/token",
        ).strip(),
        api_base_url=os.getenv(
            "GMAIL_API_BASE_URL",
            "https://gmail.googleapis.com/gmail/v1",
        ).rstrip("/"),
        request_timeout_seconds=float(
            os.getenv("GMAIL_REQUEST_TIMEOUT_SECONDS", "15")
        ),
    )


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
