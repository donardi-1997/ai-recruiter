"""add durable Indeed email resume-agent tasks

Revision ID: 011
Revises: 010
Create Date: 2026-09-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "indeed_email_resume_tasks",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("owner_sub", sa.Text(), nullable=False),
        sa.Column(
            "ingestion_event_id",
            UUID(as_uuid=False),
            sa.ForeignKey("candidate_ingestion_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            UUID(as_uuid=False),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("candidate_name", sa.Text(), nullable=False),
        sa.Column("job_title", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="WAITING_DOWNLOAD",
        ),
        sa.Column("lease_token", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "ingestion_event_id",
            name="uq_indeed_email_resume_task_event",
        ),
    )
    op.create_index(
        "idx_indeed_email_resume_task_claim",
        "indeed_email_resume_tasks",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "idx_indeed_email_resume_task_owner_status",
        "indeed_email_resume_tasks",
        ["owner_sub", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_indeed_email_resume_task_owner_status",
        table_name="indeed_email_resume_tasks",
    )
    op.drop_index(
        "idx_indeed_email_resume_task_claim",
        table_name="indeed_email_resume_tasks",
    )
    op.drop_table("indeed_email_resume_tasks")
