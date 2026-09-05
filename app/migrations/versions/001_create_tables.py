"""create tables

Revision ID: 001
Revises:
Create Date: 2026-09-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidates",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("email", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("metadata", JSONB, nullable=True, server_default="{}"),
    )
    op.create_index("idx_candidates_created_at", "candidates", [sa.text("created_at DESC")])

    op.create_table(
        "jobs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "job_candidates",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_id", UUID(as_uuid=False), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_id", UUID(as_uuid=False), sa.ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_job_candidates_job", "job_candidates", ["job_id"])
    op.create_index("idx_job_candidates_candidate", "job_candidates", ["candidate_id"])

    op.create_table(
        "evaluations",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("candidate_id", UUID(as_uuid=False), sa.ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", UUID(as_uuid=False), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("match_score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("recommendation", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("strengths", JSONB, nullable=True, server_default="[]"),
        sa.Column("gaps", JSONB, nullable=True, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "rankings",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_id", UUID(as_uuid=False), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ranking_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("mode", sa.Text, nullable=False, server_default="full"),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("idx_rankings_job_id", "rankings", ["job_id"])

    op.create_table(
        "ranking_items",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ranking_id", UUID(as_uuid=False), sa.ForeignKey("rankings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_id", UUID(as_uuid=False), sa.ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("position", sa.Integer, nullable=False),
    )
    op.create_index("idx_ranking_items_candidate", "ranking_items", ["candidate_id"])
    op.create_index("idx_ranking_items_ranking_id", "ranking_items", ["ranking_id"])


def downgrade() -> None:
    op.drop_table("ranking_items")
    op.drop_table("rankings")
    op.drop_table("evaluations")
    op.drop_table("job_candidates")
    op.drop_table("jobs")
    op.drop_table("candidates")
