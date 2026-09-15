"""PostgreSQL-only smoke coverage for the real Alembic migration chain."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def _postgres_url() -> str:
    return os.getenv("DATABASE_URL", "")


def test_alembic_head_builds_current_postgres_schema():
    url = _postgres_url()
    if not url.startswith(("postgresql://", "postgresql+")):
        pytest.skip("PostgreSQL migration smoke only")

    project_root = Path(__file__).resolve().parents[2]
    config = Config()
    config.set_main_option("script_location", str(project_root / "app" / "migrations"))
    config.set_main_option("sqlalchemy.url", url)

    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {
            "indeed_connections",
            "indeed_job_links",
            "indeed_sync_events",
            "indeed_candidate_links",
            "indeed_candidate_sync_state",
            "indeed_disposition_events",
        }.issubset(tables)

        job_columns = {column["name"] for column in inspector.get_columns("jobs")}
        assert {
            "country_code",
            "city",
            "employment_type",
            "public_slug",
            "published_at",
        }.issubset(job_columns)

        assignment_columns = {
            column["name"] for column in inspector.get_columns("job_candidates")
        }
        assert {"application_status", "status_changed_at"}.issubset(assignment_columns)

        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert revision == "005"
    finally:
        engine.dispose()
