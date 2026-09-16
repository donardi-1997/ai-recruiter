"""add job intelligence and versioned evaluations

Revision ID: 008
Revises: 007
Create Date: 2026-09-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("evaluation_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "evaluation_profile",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "evaluations",
        sa.Column(
            "job_evaluation_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )

    op.alter_column("jobs", "evaluation_version", server_default=None)
    op.alter_column("jobs", "evaluation_profile", server_default=None)
    op.alter_column("jobs", "updated_at", server_default=None)
    op.alter_column("evaluations", "job_evaluation_version", server_default=None)

    op.create_table(
        "job_reevaluation_tasks",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("owner_sub", sa.Text(), nullable=False),
        sa.Column(
            "job_id",
            UUID(as_uuid=False),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_evaluation_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("queue_dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_token", sa.Text(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "job_id",
            "target_evaluation_version",
            name="uq_job_reevaluation_job_version",
        ),
    )
    op.create_index(
        "idx_job_reevaluation_owner_created",
        "job_reevaluation_tasks",
        ["owner_sub", "created_at"],
    )
    op.create_index(
        "idx_job_reevaluation_status_heartbeat",
        "job_reevaluation_tasks",
        ["status", "heartbeat_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_job_reevaluation_status_heartbeat",
        table_name="job_reevaluation_tasks",
    )
    op.drop_index(
        "idx_job_reevaluation_owner_created",
        table_name="job_reevaluation_tasks",
    )
    op.drop_table("job_reevaluation_tasks")

    op.drop_column("evaluations", "job_evaluation_version")
    op.drop_column("jobs", "updated_at")
    op.drop_column("jobs", "evaluation_profile")
    op.drop_column("jobs", "evaluation_version")
