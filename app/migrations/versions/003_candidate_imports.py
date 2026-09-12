"""add durable candidate import tables

Revision ID: 003
Revises: 002
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("job_id", UUID(as_uuid=False), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_sub", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="UPLOADING"),
        sa.Column("current_stage", sa.Text, nullable=False, server_default="UPLOADING"),
        sa.Column("upload_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("uploaded_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processed_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("successful_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reused_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("evaluated_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("evaluation_failed_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ranking_ready", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("ranking_version", sa.Integer, nullable=True),
        sa.Column("bedrock_ingestion_job_id", sa.Text, nullable=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("queue_dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_token", sa.Text, nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text, nullable=True),
        sa.Column("last_error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "idx_import_batches_owner_created",
        "import_batches",
        ["owner_sub", "created_at"],
    )
    op.create_index(
        "idx_import_batches_job_created",
        "import_batches",
        ["job_id", "created_at"],
    )
    op.create_index(
        "idx_import_batches_status_heartbeat",
        "import_batches",
        ["status", "heartbeat_at"],
    )

    op.create_table(
        "import_items",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("batch_id", UUID(as_uuid=False), sa.ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_item_id", UUID(as_uuid=False), sa.ForeignKey("import_items.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("original_filename", sa.Text, nullable=False),
        sa.Column("staging_s3_key", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("document_sha256", sa.Text, nullable=True),
        sa.Column("candidate_id", UUID(as_uuid=False), sa.ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="UPLOADING"),
        sa.Column("current_stage", sa.Text, nullable=False, server_default="UPLOADING"),
        sa.Column("outcome", sa.Text, nullable=True),
        sa.Column("error_code", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_import_items_batch_status",
        "import_items",
        ["batch_id", "status"],
    )
    op.create_index(
        "idx_import_items_candidate",
        "import_items",
        ["candidate_id"],
    )

    op.create_table(
        "candidate_identities",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("owner_sub", sa.Text, nullable=False),
        sa.Column("candidate_id", UUID(as_uuid=False), sa.ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "owner_sub",
            "kind",
            "value",
            name="uq_candidate_identity_owner_kind_value",
        ),
    )
    op.create_index(
        "idx_candidate_identities_candidate",
        "candidate_identities",
        ["candidate_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_candidate_identities_candidate", table_name="candidate_identities")
    op.drop_table("candidate_identities")

    op.drop_index("idx_import_items_candidate", table_name="import_items")
    op.drop_index("idx_import_items_batch_status", table_name="import_items")
    op.drop_table("import_items")

    op.drop_index("idx_import_batches_status_heartbeat", table_name="import_batches")
    op.drop_index("idx_import_batches_job_created", table_name="import_batches")
    op.drop_index("idx_import_batches_owner_created", table_name="import_batches")
    op.drop_table("import_batches")
