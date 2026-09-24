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
class MassEvaluationCostSettings:
    """Planning assumptions used by the pre-run mass-evaluation calculator."""

    nova_input_usd_per_million: float
    nova_output_usd_per_million: float
    input_tokens_per_deep_candidate: int
    output_tokens_per_deep_candidate: int
    fast_default_deep_candidates: int
    cost_margin_percent: float
    max_deep_requests_per_minute: int


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
    """OAuth-backed Gmail transport settings.

    Client credentials may be empty in the environment in production. The Gmail
    integration composition layer overlays values read from Secrets Manager.
    """

    enabled: bool
    client_id: str
    client_secret: str
    refresh_token: str
    user_id: str
    query: str
    allowed_senders: tuple[str, ...]
    ingestion_provider: str
    scope: str
    token_url: str
    api_base_url: str
    request_timeout_seconds: float

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)


@dataclass(frozen=True)
class GmailOAuthSettings:
    """Non-secret settings for the single corporate Gmail OAuth connection."""

    secret_id: str
    redirect_uri: str
    frontend_return_url: str
    authorization_url: str
    token_url: str
    state_max_age_seconds: int


@dataclass(frozen=True)
class IndeedResumeAgentSettings:
    """Non-secret settings for the machine that downloads Indeed resumes."""

    secret_id: str
    lease_seconds: int
    max_attempts: int
    sender_domains: tuple[str, ...]
    resume_host_suffixes: tuple[str, ...]


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


def get_training_content_bucket() -> str:
    """Return the private bucket used for persistent training media."""
    return os.environ["TRAINING_CONTENT_BUCKET"]


def get_import_evaluation_concurrency() -> int:
    """Return the bounded number of candidate evaluations run concurrently."""
    return int(os.getenv("IMPORT_EVALUATION_CONCURRENCY", "3"))


def get_import_lease_timeout_seconds() -> int:
    """Return the stale-worker lease timeout used for crash recovery."""
    return int(os.getenv("IMPORT_LEASE_TIMEOUT_SECONDS", "300"))


def get_mass_evaluation_cost_settings() -> MassEvaluationCostSettings:
    """Return configurable pricing assumptions for mass evaluation previews."""

    return MassEvaluationCostSettings(
        nova_input_usd_per_million=float(
            os.getenv("MASS_EVAL_NOVA_INPUT_USD_PER_MILLION", "0.30")
        ),
        nova_output_usd_per_million=float(
            os.getenv("MASS_EVAL_NOVA_OUTPUT_USD_PER_MILLION", "2.50")
        ),
        input_tokens_per_deep_candidate=max(
            1,
            int(os.getenv("MASS_EVAL_INPUT_TOKENS_PER_CANDIDATE", "4500")),
        ),
        output_tokens_per_deep_candidate=max(
            1,
            int(os.getenv("MASS_EVAL_OUTPUT_TOKENS_PER_CANDIDATE", "600")),
        ),
        fast_default_deep_candidates=max(
            1,
            int(os.getenv("MASS_EVAL_FAST_DEEP_CANDIDATES", "1000")),
        ),
        cost_margin_percent=max(
            0.0,
            float(os.getenv("MASS_EVAL_COST_MARGIN_PERCENT", "25")),
        ),
        max_deep_requests_per_minute=max(
            1,
            int(os.getenv("MASS_EVAL_MAX_DEEP_REQUESTS_PER_MINUTE", "2000")),
        ),
    )


def get_gmail_settings() -> GmailSettings:
    """Return Gmail ingestion settings without ever reading a mailbox password."""
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
        ingestion_provider=(
            os.getenv("GMAIL_INGESTION_PROVIDER", "INDEED").strip().upper()
            or "INDEED"
        ),
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


def get_gmail_oauth_settings() -> GmailOAuthSettings:
    """Return non-secret corporate Gmail OAuth settings."""
    return GmailOAuthSettings(
        secret_id=os.getenv(
            "GMAIL_OAUTH_SECRET_ID",
            "/ai-recruiter/prod/gmail-oauth",
        ).strip(),
        redirect_uri=os.getenv("GMAIL_OAUTH_REDIRECT_URI", "").strip(),
        frontend_return_url=os.getenv(
            "GMAIL_OAUTH_FRONTEND_RETURN_URL",
            "https://dzcwl3yhv133t.cloudfront.net/integrations",
        ).strip(),
        authorization_url=os.getenv(
            "GMAIL_AUTHORIZATION_URL",
            "https://accounts.google.com/o/oauth2/v2/auth",
        ).strip(),
        token_url=os.getenv(
            "GMAIL_TOKEN_URL",
            "https://oauth2.googleapis.com/token",
        ).strip(),
        state_max_age_seconds=max(
            60,
            int(os.getenv("GMAIL_OAUTH_STATE_MAX_AGE_SECONDS", "600")),
        ),
    )


def get_indeed_resume_agent_settings() -> IndeedResumeAgentSettings:
    """Return non-secret resume-agent settings."""
    sender_domains = tuple(
        value.strip().casefold()
        for value in os.getenv(
            "INDEED_RESUME_AGENT_SENDER_DOMAINS",
            "indeedemail.com",
        ).split(",")
        if value.strip()
    )
    resume_host_suffixes = tuple(
        value.strip().casefold()
        for value in os.getenv(
            "INDEED_RESUME_AGENT_RESUME_HOST_SUFFIXES",
            "indeed.com,indeedemail.com",
        ).split(",")
        if value.strip()
    )
    return IndeedResumeAgentSettings(
        secret_id=os.getenv(
            "INDEED_RESUME_AGENT_SECRET_ID",
            "/ai-recruiter/prod/indeed-resume-agent",
        ).strip(),
        lease_seconds=int(os.getenv("INDEED_RESUME_AGENT_LEASE_SECONDS", "600")),
        max_attempts=int(os.getenv("INDEED_RESUME_AGENT_MAX_ATTEMPTS", "3")),
        sender_domains=sender_domains,
        resume_host_suffixes=resume_host_suffixes,
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
