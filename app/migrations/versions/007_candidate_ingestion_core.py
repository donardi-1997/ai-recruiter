"""add provider-neutral candidate ingestion core

Revision ID: 007
Revises: 006
Create Date: 2026-09-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_ingestion_events",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("owner_sub", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("source_account", sa.Text(), nullable=False, server_default=""),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column(
            "job_id",
            UUID(as_uuid=False),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "candidate_id",
            UUID(as_uuid=False),
            sa.ForeignKey("candidates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="RECEIVED"),
        sa.Column("raw_metadata", sa.JSON(), nullable=True),
        sa.Column("raw_s3_key", sa.Text(), nullable=True),
        sa.Column("bedrock_ingestion_job_id", sa.Text(), nullable=True),
        sa.Column("queue_dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_token", sa.Text(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "owner_sub",
            "source",
            "provider",
            "source_account",
            "external_id",
            name="uq_candidate_ingestion_external_event",
        ),
    )
    op.create_index(
        "idx_candidate_ingestion_owner_status",
        "candidate_ingestion_events",
        ["owner_sub", "status"],
    )
    op.create_index(
        "idx_candidate_ingestion_dispatch",
        "candidate_ingestion_events",
        ["status", "queue_dispatched_at"],
    )
    op.create_index(
        "idx_candidate_ingestion_job_created",
        "candidate_ingestion_events",
        ["job_id", "created_at"],
    )

    op.create_table(
        "candidate_ingestion_documents",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "ingestion_event_id",
            UUID(as_uuid=False),
            sa.ForeignKey("candidate_ingestion_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("source_s3_key", sa.Text(), nullable=False),
        sa.Column("document_sha256", sa.Text(), nullable=True),
        sa.Column("canonical_s3_key", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="STORED"),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_candidate_ingestion_documents_event_status",
        "candidate_ingestion_documents",
        ["ingestion_event_id", "status"],
    )
    op.create_index(
        "idx_candidate_ingestion_documents_sha",
        "candidate_ingestion_documents",
        ["document_sha256"],
    )

    op.create_table(
        "candidate_ingestion_cursors",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("owner_sub", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("source_account", sa.Text(), nullable=False),
        sa.Column("cursor_value", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
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
            "owner_sub",
            "source",
            "provider",
            "source_account",
            name="uq_candidate_ingestion_cursor_source",
        ),
    )
    op.create_index(
        "idx_candidate_ingestion_cursor_owner",
        "candidate_ingestion_cursors",
        ["owner_sub", "source", "provider"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_candidate_ingestion_cursor_owner",
        table_name="candidate_ingestion_cursors",
    )
    op.drop_table("candidate_ingestion_cursors")

    op.drop_index(
        "idx_candidate_ingestion_documents_sha",
        table_name="candidate_ingestion_documents",
    )
    op.drop_index(
        "idx_candidate_ingestion_documents_event_status",
        table_name="candidate_ingestion_documents",
    )
    op.drop_table("candidate_ingestion_documents")

    op.drop_index(
        "idx_candidate_ingestion_job_created",
        table_name="candidate_ingestion_events",
    )
    op.drop_index(
        "idx_candidate_ingestion_dispatch",
        table_name="candidate_ingestion_events",
    )
    op.drop_index(
        "idx_candidate_ingestion_owner_status",
        table_name="candidate_ingestion_events",
    )
    op.drop_table("candidate_ingestion_events")
