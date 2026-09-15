"""add durable Indeed resume ingestion state

Revision ID: 006
Revises: 005
Create Date: 2026-09-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "indeed_resume_ingestions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("owner_sub", sa.Text(), nullable=False),
        sa.Column(
            "candidate_link_id",
            UUID(as_uuid=False),
            sa.ForeignKey("indeed_candidate_links.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("resume_sha256", sa.Text(), nullable=True),
        sa.Column("canonical_s3_key", sa.Text(), nullable=True),
        sa.Column("bedrock_ingestion_job_id", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("queue_dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_token", sa.Text(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "candidate_link_id",
            name="uq_indeed_resume_ingestions_candidate_link",
        ),
    )
    op.create_index(
        "idx_indeed_resume_ingestions_owner_status",
        "indeed_resume_ingestions",
        ["owner_sub", "status"],
    )
    op.create_index(
        "idx_indeed_resume_ingestions_dispatch",
        "indeed_resume_ingestions",
        ["status", "queue_dispatched_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_indeed_resume_ingestions_dispatch",
        table_name="indeed_resume_ingestions",
    )
    op.drop_index(
        "idx_indeed_resume_ingestions_owner_status",
        table_name="indeed_resume_ingestions",
    )
    op.drop_table("indeed_resume_ingestions")
