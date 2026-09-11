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
