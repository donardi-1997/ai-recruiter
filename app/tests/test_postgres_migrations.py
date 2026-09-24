"""PostgreSQL-only smoke coverage for the real Alembic migration chain."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

import app.models  # noqa: F401 - register ORM tables in Base.metadata
from app.db import Base


CORE_TABLES = {
    "candidates",
    "jobs",
    "job_candidates",
    "evaluations",
    "rankings",
    "ranking_items",
    "user_profiles",
    "roles",
    "permissions",
    "user_roles",
    "role_permissions",
    "employee_score_events",
    "training_courses",
    "training_modules",
    "training_lessons",
    "training_assignments",
    "training_lesson_progress",
    "training_quizzes",
    "training_quiz_questions",
    "training_quiz_attempts",
    "candidate_restriction_events",
}


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
            "indeed_resume_ingestions",
            "candidate_ingestion_events",
            "candidate_ingestion_documents",
            "indeed_email_resume_tasks",
            "job_reevaluation_tasks",
            "company_contexts",
            "user_profiles",
            "roles",
            "permissions",
            "user_roles",
            "role_permissions",
            "employee_score_events",
            "training_courses",
            "training_modules",
            "training_lessons",
            "training_assignments",
            "training_lesson_progress",
            "training_quizzes",
            "training_quiz_questions",
            "training_quiz_attempts",
            "candidate_restriction_events",
        }.issubset(tables)

        for table_name in sorted(CORE_TABLES):
            assert table_name in tables
            database_columns = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            orm_columns = set(Base.metadata.tables[table_name].columns.keys())
            missing_columns = orm_columns - database_columns
            assert not missing_columns, (
                f"Alembic head is missing ORM columns for {table_name}: "
                f"{sorted(missing_columns)}"
            )

        resume_columns = {
            column["name"] for column in inspector.get_columns("indeed_resume_ingestions")
        }
        assert {
            "candidate_link_id",
            "status",
            "resume_sha256",
            "canonical_s3_key",
            "bedrock_ingestion_job_id",
            "attempt_count",
            "queue_dispatched_at",
            "processing_token",
            "heartbeat_at",
            "last_error_code",
            "last_error_message",
            "completed_at",
        }.issubset(resume_columns)

        ingestion_event_columns = {
            column["name"]
            for column in inspector.get_columns("candidate_ingestion_events")
        }
        assert {
            "owner_sub",
            "source",
            "provider",
            "external_id",
            "job_id",
            "candidate_id",
            "status",
            "raw_metadata",
            "raw_s3_key",
            "queue_dispatched_at",
            "processing_token",
            "heartbeat_at",
            "attempt_count",
            "last_error_code",
            "last_error_message",
            "completed_at",
        }.issubset(ingestion_event_columns)

        indeed_email_task_columns = {
            column["name"]
            for column in inspector.get_columns("indeed_email_resume_tasks")
        }
        assert {
            "owner_sub",
            "ingestion_event_id",
            "job_id",
            "candidate_name",
            "job_title",
            "status",
            "lease_token",
            "lease_expires_at",
            "claimed_at",
            "available_at",
            "attempt_count",
            "last_error_code",
            "last_error_message",
            "completed_at",
            "created_at",
            "updated_at",
        }.issubset(indeed_email_task_columns)

        indeed_candidate_link_columns = {
            column["name"] for column in inspector.get_columns("indeed_candidate_links")
        }
        assert "staged_at" in indeed_candidate_link_columns

        indeed_job_link_columns = {
            column["name"] for column in inspector.get_columns("indeed_job_links")
        }
        assert "discovery_key" in indeed_job_link_columns
        indeed_job_link_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("indeed_job_links")
        }
        assert "uq_indeed_job_links_owner_discovery_key" in indeed_job_link_uniques

        job_candidate_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("job_candidates")
        }
        assert "uq_job_candidates_job_candidate" in job_candidate_uniques

        evaluation_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("evaluations")
        }
        assert "uq_evaluations_job_candidate" in evaluation_uniques

        company_context_columns = {
            column["name"] for column in inspector.get_columns("company_contexts")
        }
        assert {
            "owner_sub",
            "organization_name",
            "version",
            "status",
            "context",
            "created_at",
            "updated_at",
        }.issubset(company_context_columns)

        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            role_codes = {
                row[0]
                for row in connection.execute(
                    text("SELECT code FROM roles")
                ).all()
            }
            score_grants = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT permission_code FROM role_permissions "
                        "WHERE role_code = 'SUPER_ADMIN' "
                        "AND permission_code LIKE 'employee_scores.%'"
                    )
                ).all()
            }
            admin_score_grants = connection.execute(
                text(
                    "SELECT COUNT(*) FROM role_permissions "
                    "WHERE role_code = 'ADMIN' "
                    "AND permission_code LIKE 'employee_scores.%'"
                )
            ).scalar_one()
        candidate_columns = {
            column["name"] for column in inspector.get_columns("candidates")
        }
        assert {
            "is_banned",
            "banned_at",
            "banned_by_sub",
            "banned_reason",
        }.issubset(candidate_columns)

        restriction_event_columns = {
            column["name"]
            for column in inspector.get_columns("candidate_restriction_events")
        }
        assert {
            "candidate_id",
            "action",
            "reason",
            "created_by_sub",
            "created_at",
        }.issubset(restriction_event_columns)

        job_columns = {column["name"] for column in inspector.get_columns("jobs")}
        assert {"indeed_description", "ai_description", "active_description_source"}.issubset(job_columns)

        assert role_codes == {"SUPER_ADMIN", "ADMIN", "EMPLOYEE"}
        assert score_grants == {
            "employee_scores.read",
            "employee_scores.create",
            "employee_scores.correct",
            "employee_scores.export",
        }
        score_event_columns = {
            column["name"]
            for column in inspector.get_columns("employee_score_events")
        }
        assert {
            "employee_id",
            "points",
            "description",
            "status",
            "event_date",
            "created_by_sub",
            "created_at",
            "voided_at",
            "voided_by_sub",
            "void_reason",
        }.issubset(score_event_columns)

        user_profile_columns = {
            column["name"]
            for column in inspector.get_columns("user_profiles")
        }
        assert {
            "hire_date",
            "onboarding_status",
            "onboarding_started_at",
            "onboarding_completed_at",
        }.issubset(user_profile_columns)

        training_course_columns = {
            column["name"]
            for column in inspector.get_columns("training_courses")
        }
        assert "is_onboarding" in training_course_columns

        training_module_columns = {
            column["name"]
            for column in inspector.get_columns("training_modules")
        }
        assert {
            "audience_job_title",
            "audience_department",
        }.issubset(training_module_columns)

        training_lesson_columns = {
            column["name"]
            for column in inspector.get_columns("training_lessons")
        }
        assert {
            "video_storage_key",
            "video_content_type",
            "video_size_bytes",
            "content_type",
            "external_url",
            "estimated_minutes",
            "checklist_items",
            "is_optional",
        }.issubset(training_lesson_columns)

        training_progress_columns = {
            column["name"]
            for column in inspector.get_columns("training_lesson_progress")
        }
        assert "details" in training_progress_columns

        assert admin_score_grants == 0
        assert revision == "024"
    finally:
        engine.dispose()
