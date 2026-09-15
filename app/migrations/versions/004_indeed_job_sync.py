"""add Indeed Job Sync integration tables

Revision ID: 004
Revises: 003
Create Date: 2026-09-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("country_code", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("city", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("employment_type", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("public_slug", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "indeed_connections",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("owner_sub", sa.Text(), nullable=False),
        sa.Column("employer_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="DISCONNECTED"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_sub", name="uq_indeed_connections_owner"),
    )

    op.create_table(
        "indeed_job_links",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("job_id", UUID(as_uuid=False), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_sub", sa.Text(), nullable=False),
        sa.Column("sourced_posting_id", sa.Text(), nullable=True),
        sa.Column("employer_job_id", sa.Text(), nullable=True),
        sa.Column("external_status", sa.JSON(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("job_id", name="uq_indeed_job_links_job"),
    )
    op.create_index("idx_indeed_job_links_owner", "indeed_job_links", ["owner_sub"])

    op.create_table(
        "indeed_sync_events",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("owner_sub", sa.Text(), nullable=False),
        sa.Column("job_id", UUID(as_uuid=False), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_indeed_sync_events_owner_created", "indeed_sync_events", ["owner_sub", "created_at"])
    op.create_index("idx_indeed_sync_events_job_created", "indeed_sync_events", ["job_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_indeed_sync_events_job_created", table_name="indeed_sync_events")
    op.drop_index("idx_indeed_sync_events_owner_created", table_name="indeed_sync_events")
    op.drop_table("indeed_sync_events")
    op.drop_index("idx_indeed_job_links_owner", table_name="indeed_job_links")
    op.drop_table("indeed_job_links")
    op.drop_table("indeed_connections")
    op.drop_column("jobs", "published_at")
    op.drop_column("jobs", "public_slug")
    op.drop_column("jobs", "employment_type")
    op.drop_column("jobs", "city")
    op.drop_column("jobs", "country_code")
