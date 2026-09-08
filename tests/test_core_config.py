"""Tests for core/config.py."""

import os


def test_config_loads_env_vars():
    """Config module should load environment variables."""
    from core.config import AWS_REGION, COGNITO_CLIENT_ID

    assert AWS_REGION is not None
    assert COGNITO_CLIENT_ID is not None


def test_config_has_cognito_urls():
    """Config should build Cognito URLs from env vars."""
    from core.config import COGNITO_ISSUER, COGNITO_JWKS_URL

    assert "cognito-idp" in COGNITO_ISSUER
    assert ".well-known/jwks.json" in COGNITO_JWKS_URL


def test_config_table_names():
    """Config should define all DynamoDB table names."""
    from core.config import (
        CANDIDATES_TABLE,
        JOBS_TABLE,
        EVALUATIONS_TABLE,
        JOB_CANDIDATES_TABLE,
        RANKINGS_TABLE,
    )

    assert CANDIDATES_TABLE == "ai-recruiter-candidates"
    assert JOBS_TABLE == "ai-recruiter-jobs"
    assert EVALUATIONS_TABLE == "ai-recruiter-evaluations"
    assert RANKINGS_TABLE == "ai-recruiter-rankings"


def test_config_cors_origins():
    """Config should define CORS origins including localhost and production."""
    from core.config import CORS_ORIGINS

    assert any("localhost" in o for o in CORS_ORIGINS)
    assert any("cloudfront" in o for o in CORS_ORIGINS)


def test_config_constants():
    """Config should define numeric constants."""
    from core.config import NUMBER_OF_RESULTS, MAX_CV_SIZE_BYTES

    assert NUMBER_OF_RESULTS > 0
    assert MAX_CV_SIZE_BYTES > 0
