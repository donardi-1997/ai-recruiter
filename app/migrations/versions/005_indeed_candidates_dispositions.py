"""add Indeed candidate sync and disposition persistence

Revision ID: 005
Revises: 004
Create Date: 2026-09-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_candidates",
        sa.Column("application_status", sa.Text(), nullable=False, server_default="APPLIED"),
    )
    op.add_column(
        "job_candidates",
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE job_candidates SET status_changed_at = assigned_at WHERE status_changed_at IS NULL")
    op.alter_column("job_candidates", "status_changed_at", nullable=False)

    op.create_table(
        "indeed_candidate_links",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("owner_sub", sa.Text(), nullable=False),
        sa.Column("candidate_id", UUID(as_uuid=False), sa.ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", UUID(as_uuid=False), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("registration_id", sa.Text(), nullable=True),
        sa.Column("employer_identifier", sa.Text(), nullable=True),
        sa.Column("source_enum_key", sa.Text(), nullable=True),
        sa.Column("source_name", sa.Text(), nullable=True),
        sa.Column("sourced_posting_id", sa.Text(), nullable=True),
        sa.Column("indeed_apply_id", sa.Text(), nullable=True),
        sa.Column("ittk", sa.Text(), nullable=True),
        sa.Column("universal_apply_id", sa.Text(), nullable=True),
        sa.Column("resume_name", sa.Text(), nullable=True),
        sa.Column("resume_url", sa.Text(), nullable=True),
        sa.Column("staged_test", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_sub", "asset_id", name="uq_indeed_candidate_links_owner_asset"),
    )
    op.create_index("idx_indeed_candidate_links_owner_job", "indeed_candidate_links", ["owner_sub", "job_id"])
    op.create_index("idx_indeed_candidate_links_candidate", "indeed_candidate_links", ["candidate_id"])

    op.create_table(
        "indeed_candidate_sync_state",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("owner_sub", sa.Text(), nullable=False),
        sa.Column("ack_token", sa.Text(), nullable=True),
        sa.Column("last_fetch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ack_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_sub", name="uq_indeed_candidate_sync_state_owner"),
    )

    op.create_table(
        "indeed_disposition_events",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("owner_sub", sa.Text(), nullable=False),
        sa.Column("candidate_link_id", UUID(as_uuid=False), sa.ForeignKey("indeed_candidate_links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("local_status", sa.Text(), nullable=False),
        sa.Column("indeed_status", sa.Text(), nullable=False),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sync_status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "candidate_link_id",
            "local_status",
            "status_changed_at",
            name="uq_indeed_disposition_event_state_time",
        ),
    )
    op.create_index(
        "idx_indeed_disposition_events_owner_status_time",
        "indeed_disposition_events",
        ["owner_sub", "sync_status", "status_changed_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_indeed_disposition_events_owner_status_time", table_name="indeed_disposition_events")
    op.drop_table("indeed_disposition_events")
    op.drop_table("indeed_candidate_sync_state")
    op.drop_index("idx_indeed_candidate_links_candidate", table_name="indeed_candidate_links")
    op.drop_index("idx_indeed_candidate_links_owner_job", table_name="indeed_candidate_links")
    op.drop_table("indeed_candidate_links")
    op.drop_column("job_candidates", "status_changed_at")
    op.drop_column("job_candidates", "application_status")
