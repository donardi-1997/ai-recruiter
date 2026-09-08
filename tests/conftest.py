"""Test configuration and fixtures for the DynamoDB backend."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# ENV FIXTURES
# ============================================================


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    """Set required environment variables for all tests."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "us-east-1_TEST123")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "test-kb-id")
    monkeypatch.setenv("DATA_SOURCE_ID", "test-ds-id")


# ============================================================
# AWS MOCK FIXTURES
# ============================================================


@pytest.fixture
def mock_dynamodb_table():
    """Create a mock DynamoDB table."""
    table = MagicMock()
    table.get_item.return_value = {"Item": None}
    table.put_item.return_value = {}
    table.delete_item.return_value = {}
    table.scan.return_value = {"Items": []}
    table.query.return_value = {"Items": []}
    return table


@pytest.fixture
def mock_s3():
    """Create a mock S3 client."""
    s3 = MagicMock()
    s3.put_object.return_value = {}
    s3.delete_object.return_value = {}
    s3.generate_presigned_url.return_value = "https://example.com/presigned"
    return s3


@pytest.fixture
def mock_bedrock_agent():
    """Create a mock Bedrock Agent client."""
    agent = MagicMock()
    agent.start_ingestion_job.return_value = {
        "ingestionJob": {
            "ingestionJobId": "test-ingestion-id",
            "status": "STARTING",
        }
    }
    agent.get_ingestion_job.return_value = {
        "ingestionJob": {
            "ingestionJobId": "test-ingestion-id",
            "status": "COMPLETE",
        }
    }
    return agent


@pytest.fixture
def mock_bedrock_agent_runtime():
    """Create a mock Bedrock Agent Runtime client."""
    runtime = MagicMock()
    runtime.retrieve.return_value = {
        "retrievalResults": [
            {
                "content": {"text": "Python developer with 5 years experience"},
                "location": {"s3Location": {"uri": "s3://bucket/doc.pdf"}},
                "metadata": {"candidate_id": "test-candidate-id"},
                "score": 0.95,
            }
        ]
    }
    return runtime


@pytest.fixture
def mock_cognito_client():
    """Create a mock Cognito client."""
    client = MagicMock()
    client.sign_up.return_value = {
        "UserSub": "test-user-sub",
        "UserConfirmed": False,
    }
    client.initiate_auth.return_value = {
        "AuthenticationResult": {
            "AccessToken": "test-access-token",
            "IdToken": "test-id-token",
            "RefreshToken": "test-refresh-token",
            "ExpiresIn": 3600,
        }
    }
    client.confirm_sign_up.return_value = {}
    return client


# ============================================================
# AUTH FIXTURES
# ============================================================


@pytest.fixture
def mock_current_user():
    """A mock authenticated user payload."""
    return {
        "sub": "test-user-sub-123",
        "username": "testuser",
        "token_use": "access",
        "client_id": "test-client-id",
    }


@pytest.fixture
def auth_headers():
    """Authorization headers with a Bearer token."""
    return {"Authorization": "Bearer test-token"}


# ============================================================
# APP FIXTURE
# ============================================================


@pytest.fixture
def app(
    mock_dynamodb_table,
    mock_s3,
    mock_bedrock_agent,
    mock_bedrock_agent_runtime,
    mock_cognito_client,
    mock_current_user,
):
    """Create a FastAPI test app with all AWS services mocked."""
    # Patch at ALL locations where the objects are referenced
    patches = [
        # core.aws_clients (definition)
        patch("core.aws_clients.candidates_table", mock_dynamodb_table),
        patch("core.aws_clients.jobs_table", mock_dynamodb_table),
        patch("core.aws_clients.evaluations_table", mock_dynamodb_table),
        patch("core.aws_clients.job_candidates_table", mock_dynamodb_table),
        patch("core.aws_clients.rankings_table", mock_dynamodb_table),
        patch("core.aws_clients.s3", mock_s3),
        patch("core.aws_clients.bedrock_agent", mock_bedrock_agent),
        patch("core.aws_clients.bedrock_agent_runtime", mock_bedrock_agent_runtime),
        # core.helpers (imported references)
        patch("core.helpers.candidates_table", mock_dynamodb_table),
        patch("core.helpers.jobs_table", mock_dynamodb_table),
        patch("core.helpers.evaluations_table", mock_dynamodb_table),
        patch("core.helpers.job_candidates_table", mock_dynamodb_table),
        patch("core.helpers.rankings_table", mock_dynamodb_table),
        # core.aws_clients helper functions
        patch("core.aws_clients.ensure_rankings_table_exists", return_value=True),
        # core.cognito
        patch("core.cognito.cognito_client", mock_cognito_client),
        # routers.candidates
        patch("routers.candidates.s3", mock_s3),
        patch("routers.candidates.bedrock_agent", mock_bedrock_agent),
        # routers.jobs
        patch("routers.jobs.jobs_table", mock_dynamodb_table),
        patch("routers.jobs.candidates_table", mock_dynamodb_table),
        patch("routers.jobs.evaluations_table", mock_dynamodb_table),
        # routers.evaluations
        patch("routers.evaluations.evaluations_table", mock_dynamodb_table),
        patch("routers.evaluations.candidates_table", mock_dynamodb_table),
        # routers.rankings
        patch("routers.rankings.candidates_table", mock_dynamodb_table),
        patch("routers.rankings.evaluations_table", mock_dynamodb_table),
    ]

    for p in patches:
        p.start()

    from core.auth import get_current_user
    from main import app

    app.dependency_overrides[get_current_user] = lambda: mock_current_user

    yield app

    app.dependency_overrides.clear()
    for p in patches:
        p.stop()


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)
