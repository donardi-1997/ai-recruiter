"""add independent Indeed and AI job descriptions

Revision ID: 014
Revises: 013
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa


revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("indeed_description", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("ai_description", sa.Text(), nullable=True))
    op.add_column(
        "jobs",
        sa.Column(
            "active_description_source",
            sa.Text(),
            nullable=False,
            server_default="indeed",
        ),
    )

    # Existing descriptions remain available as the original/source copy.
    op.execute(
        """
        UPDATE jobs
        SET indeed_description = description
        WHERE description IS NOT NULL
          AND indeed_description IS NULL
        """
    )

    # Jobs enriched with structured AI criteria are most likely using the
    # generated description today. Preserve that effective state during the
    # migration instead of changing candidate evaluation semantics.
    op.execute(
        """
        UPDATE jobs
        SET ai_description = description,
            active_description_source = 'ai'
        WHERE description IS NOT NULL
          AND evaluation_profile IS NOT NULL
          AND evaluation_profile::jsonb <> '{}'::jsonb
        """
    )

    op.create_check_constraint(
        "ck_jobs_active_description_source",
        "jobs",
        "active_description_source IN ('indeed', 'ai')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_jobs_active_description_source",
        "jobs",
        type_="check",
    )
    op.drop_column("jobs", "active_description_source")
    op.drop_column("jobs", "ai_description")
    op.drop_column("jobs", "indeed_description")
