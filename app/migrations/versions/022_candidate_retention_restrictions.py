"""add candidate retention and restriction audit

Revision ID: 022
Revises: 021
Create Date: 2026-09-24
"""

from alembic import op
import sqlalchemy as sa


revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidates",
        sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "candidates",
        sa.Column("banned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "candidates",
        sa.Column("banned_by_sub", sa.Text(), nullable=True),
    )
    op.add_column(
        "candidates",
        sa.Column("banned_reason", sa.Text(), nullable=True),
    )

    op.create_table(
        "candidate_restriction_events",
        sa.Column("id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("candidate_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by_sub", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_candidate_restriction_events_candidate_created",
        "candidate_restriction_events",
        ["candidate_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_candidate_restriction_events_candidate_created",
        table_name="candidate_restriction_events",
    )
    op.drop_table("candidate_restriction_events")
    op.drop_column("candidates", "banned_reason")
    op.drop_column("candidates", "banned_by_sub")
    op.drop_column("candidates", "banned_at")
    op.drop_column("candidates", "is_banned")
