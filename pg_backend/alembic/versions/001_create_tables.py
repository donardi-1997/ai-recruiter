"""create initial tables

Revision ID: 001
Revises:
Create Date: 2026-09-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── REEMPLAZAR_DB_TABLE_CANDIDATES ─────────────────────────
    op.create_table(
        "REEMPLAZAR_DB_TABLE_CANDIDATES",
        sa.Column("candidate_id",        sa.String(36), primary_key=True),
        sa.Column("owner_id",            sa.String(64), nullable=False, index=True),
        sa.Column("name",                sa.Text,       nullable=False),
        sa.Column("filename",            sa.Text,       nullable=False),
        sa.Column("s3_location",         sa.Text,       nullable=False),
        sa.Column("metadata_location",   sa.Text),
        sa.Column("ingestion_job_id",    sa.Text),
        sa.Column("ingestion_status",    sa.Text),
        sa.Column("indexed",             sa.Boolean,    nullable=False, server_default="false"),
        sa.Column("created_at",          sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at",          sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_candidates_owner", "REEMPLAZAR_DB_TABLE_CANDIDATES", ["owner_id"])

    # ── REEMPLAZAR_DB_TABLE_JOBS ───────────────────────────────
    op.create_table(
        "REEMPLAZAR_DB_TABLE_JOBS",
        sa.Column("job_id",       sa.String(36), primary_key=True),
        sa.Column("owner_id",     sa.String(64), nullable=False, index=True),
        sa.Column("title",        sa.Text,       nullable=False),
        sa.Column("description",  sa.Text,       nullable=False),
        sa.Column("created_at",   sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at",   sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_jobs_owner", "REEMPLAZAR_DB_TABLE_JOBS", ["owner_id"])

    # ── REEMPLAZAR_DB_TABLE_JOB_CANDIDATES ─────────────────────
    op.create_table(
        "REEMPLAZAR_DB_TABLE_JOB_CANDIDATES",
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("REEMPLAZAR_DB_TABLE_JOBS.job_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "candidate_id",
            sa.String(36),
            sa.ForeignKey("REEMPLAZAR_DB_TABLE_CANDIDATES.candidate_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("owner_id",     sa.String(64), nullable=False, index=True),
        sa.Column("status",       sa.String(30), nullable=False, server_default="PENDING_EVALUATION"),
        sa.Column("assigned_at",  sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_job_candidates_candidate", "REEMPLAZAR_DB_TABLE_JOB_CANDIDATES", ["candidate_id"])
    op.create_index("idx_job_candidates_owner", "REEMPLAZAR_DB_TABLE_JOB_CANDIDATES", ["owner_id"])

    # ── REEMPLAZAR_DB_TABLE_EVALUATIONS ────────────────────────
    op.create_table(
        "REEMPLAZAR_DB_TABLE_EVALUATIONS",
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("REEMPLAZAR_DB_TABLE_JOBS.job_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "candidate_id",
            sa.String(36),
            sa.ForeignKey("REEMPLAZAR_DB_TABLE_CANDIDATES.candidate_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("owner_id",        sa.String(64), nullable=False, index=True),
        sa.Column("job_title",       sa.Text,       nullable=False, server_default=""),
        sa.Column("job_description", sa.Text,       nullable=False, server_default=""),
        sa.Column("candidate_name",  sa.Text,       nullable=False, server_default=""),
        sa.Column("status",          sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("evaluated_at",    sa.DateTime(timezone=True)),
        sa.Column("match_score",     sa.Integer,    nullable=False, server_default="0"),
        sa.Column("recommendation",  sa.String(20), nullable=False, server_default="LOW_MATCH"),
        sa.Column("requirements",    JSONB,         nullable=False, server_default="[]"),
        sa.Column("strengths",       JSONB,         nullable=False, server_default="[]"),
        sa.Column("gaps",            JSONB,         nullable=False, server_default="[]"),
        sa.Column("summary",         sa.Text,       nullable=False, server_default=""),
    )
    op.create_index("idx_evaluations_candidate", "REEMPLAZAR_DB_TABLE_EVALUATIONS", ["candidate_id"])
    op.create_index("idx_evaluations_owner",     "REEMPLAZAR_DB_TABLE_EVALUATIONS", ["owner_id"])
    op.create_index("idx_evaluations_score",     "REEMPLAZAR_DB_TABLE_EVALUATIONS", [sa.text("match_score DESC")])
    op.create_index("idx_evaluations_recommendation", "REEMPLAZAR_DB_TABLE_EVALUATIONS", ["recommendation"])
    op.create_index(
        "idx_evaluations_job_score",
        "REEMPLAZAR_DB_TABLE_EVALUATIONS",
        ["job_id", sa.text("match_score DESC")],
    )

    # ── REEMPLAZAR_DB_TABLE_RANKINGS ───────────────────────────
    op.create_table(
        "REEMPLAZAR_DB_TABLE_RANKINGS",
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("REEMPLAZAR_DB_TABLE_JOBS.job_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ranking_generated_at", sa.DateTime(timezone=True)),
        sa.Column("ranking_version",      sa.Integer, nullable=False, server_default="0"),
    )

    # ── REEMPLAZAR_DB_TABLE_RANKING_ITEMS ──────────────────────
    op.create_table(
        "REEMPLAZAR_DB_TABLE_RANKING_ITEMS",
        sa.Column("id",             sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("REEMPLAZAR_DB_TABLE_JOBS.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("candidate_id",    sa.String(36), nullable=False),
        sa.Column("candidate_name",  sa.Text,       nullable=False, server_default=""),
        sa.Column("match_score",     sa.Integer,    nullable=False, server_default="0"),
        sa.Column("recommendation",  sa.String(20), nullable=False, server_default="LOW_MATCH"),
        sa.Column("rank_position",   sa.Integer,    nullable=False),
        sa.Column("strengths",       JSONB,         nullable=False, server_default="[]"),
        sa.Column("gaps",            JSONB,         nullable=False, server_default="[]"),
        sa.Column("ranking_version", sa.Integer,    nullable=False),
        sa.Column("created_at",      sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_ranking_items_job", "REEMPLAZAR_DB_TABLE_RANKING_ITEMS", ["job_id"])
    op.create_unique_constraint(
        "uq_ranking_item_per_version",
        "REEMPLAZAR_DB_TABLE_RANKING_ITEMS",
        ["job_id", "ranking_version", "candidate_id"],
    )


def downgrade() -> None:
    op.drop_table("REEMPLAZAR_DB_TABLE_RANKING_ITEMS")
    op.drop_table("REEMPLAZAR_DB_TABLE_RANKINGS")
    op.drop_table("REEMPLAZAR_DB_TABLE_EVALUATIONS")
    op.drop_table("REEMPLAZAR_DB_TABLE_JOB_CANDIDATES")
    op.drop_table("REEMPLAZAR_DB_TABLE_JOBS")
    op.drop_table("REEMPLAZAR_DB_TABLE_CANDIDATES")
