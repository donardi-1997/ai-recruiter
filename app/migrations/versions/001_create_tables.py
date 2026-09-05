"""create tables

Revision ID: 001
Revises:
Create Date: 2026-09-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── REEMPLAZAR_DB_TABLE_CANDIDATES ─────────────────────────
    op.create_table(
        "REEMPLAZAR_DB_TABLE_CANDIDATES",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name",       sa.Text, nullable=False),
        sa.Column("email",      sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("metadata",   JSONB,  nullable=True, server_default="{}"),
    )
    op.create_index(
        "idx_candidates_created_at",
        "REEMPLAZAR_DB_TABLE_CANDIDATES",
        [sa.text("created_at DESC")],
    )

    # ── REEMPLAZAR_DB_TABLE_JOBS ───────────────────────────────
    op.create_table(
        "REEMPLAZAR_DB_TABLE_JOBS",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title",      sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── REEMPLAZAR_DB_TABLE_RANKINGS ───────────────────────────
    op.create_table(
        "REEMPLAZAR_DB_TABLE_RANKINGS",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "job_id",
            UUID(as_uuid=False),
            sa.ForeignKey("REEMPLAZAR_DB_TABLE_JOBS.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ranking_version", sa.Integer,  nullable=False, server_default="0"),
        sa.Column("generated_at",    sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("mode",            sa.Text,     nullable=False, server_default="full"),
        sa.Column("notes",           sa.Text,     nullable=True),
    )
    op.create_index(
        "idx_rankings_job_id",
        "REEMPLAZAR_DB_TABLE_RANKINGS",
        ["job_id"],
    )

    # ── REEMPLAZAR_DB_TABLE_RANKING_ITEMS ──────────────────────
    op.create_table(
        "REEMPLAZAR_DB_TABLE_RANKING_ITEMS",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "ranking_id",
            UUID(as_uuid=False),
            sa.ForeignKey("REEMPLAZAR_DB_TABLE_RANKINGS.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            UUID(as_uuid=False),
            sa.ForeignKey("REEMPLAZAR_DB_TABLE_CANDIDATES.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score",    sa.Float, nullable=False, server_default="0.0"),
        sa.Column("position", sa.Integer, nullable=False),
    )
    op.create_index(
        "idx_ranking_items_candidate",
        "REEMPLAZAR_DB_TABLE_RANKING_ITEMS",
        ["candidate_id"],
    )
    op.create_index(
        "idx_ranking_items_ranking_id",
        "REEMPLAZAR_DB_TABLE_RANKING_ITEMS",
        ["ranking_id"],
    )


def downgrade() -> None:
    op.drop_table("REEMPLAZAR_DB_TABLE_RANKING_ITEMS")
    op.drop_table("REEMPLAZAR_DB_TABLE_RANKINGS")
    op.drop_table("REEMPLAZAR_DB_TABLE_JOBS")
    op.drop_table("REEMPLAZAR_DB_TABLE_CANDIDATES")
