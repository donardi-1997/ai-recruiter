import app.config as config
from app.config import CORS_ORIGINS, get_aws_region, get_database_url


def test_aws_region_defaults_to_us_east_2(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    assert get_aws_region() == "us-east-2"


def test_aws_region_reads_existing_environment_name(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    assert get_aws_region() == "us-west-2"


def test_database_url_reads_existing_environment_name(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/test")
    assert get_database_url() == "postgresql://example/test"


def test_database_url_defaults_to_empty_string(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert get_database_url() == ""


def test_cors_origins_preserve_public_contract():
    assert CORS_ORIGINS == (
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "https://ai.adrianguerra.net",
        "https://air.adrianguerra.net",
    )


def test_import_storage_and_queue_are_required(monkeypatch):
    monkeypatch.setenv("IMPORT_STAGING_BUCKET", "staging")
    monkeypatch.setenv("IMPORT_QUEUE_URL", "https://queue.example")
    assert config.get_import_staging_bucket() == "staging"
    assert config.get_import_queue_url() == "https://queue.example"


def test_import_worker_defaults(monkeypatch):
    monkeypatch.delenv("IMPORT_EVALUATION_CONCURRENCY", raising=False)
    monkeypatch.delenv("IMPORT_LEASE_TIMEOUT_SECONDS", raising=False)
    assert config.get_import_evaluation_concurrency() == 3
    assert config.get_import_lease_timeout_seconds() == 300


def test_import_worker_overrides(monkeypatch):
    monkeypatch.setenv("IMPORT_EVALUATION_CONCURRENCY", "5")
    monkeypatch.setenv("IMPORT_LEASE_TIMEOUT_SECONDS", "600")
    assert config.get_import_evaluation_concurrency() == 5
    assert config.get_import_lease_timeout_seconds() == 600
