"""Stable environment-derived application configuration."""

import os

DEFAULT_AWS_REGION = "us-east-2"

CORS_ORIGINS = (
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "https://ai.adrianguerra.net",
    "https://air.adrianguerra.net",
)


def get_aws_region() -> str:
    """Return the configured AWS region without caching environment state."""
    return os.getenv("AWS_REGION", DEFAULT_AWS_REGION)


def get_database_url() -> str:
    """Return DATABASE_URL using the existing empty-string default."""
    return os.getenv("DATABASE_URL", "")
