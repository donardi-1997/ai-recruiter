"""add onboarding journey metadata

Revision ID: 023
Revises: 022
Create Date: 2026-09-24
"""

from alembic import op
import sqlalchemy as sa


revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "training_modules",
        sa.Column("audience_job_title", sa.Text(), nullable=True),
    )
    op.add_column(
        "training_modules",
        sa.Column("audience_department", sa.Text(), nullable=True),
    )
    op.add_column(
        "training_lessons",
        sa.Column(
            "content_type",
            sa.Text(),
            nullable=False,
            server_default="VIDEO",
        ),
    )
    op.add_column(
        "training_lessons",
        sa.Column("external_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "training_lessons",
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "training_lessons",
        sa.Column(
            "is_optional",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("training_lessons", "is_optional")
    op.drop_column("training_lessons", "estimated_minutes")
    op.drop_column("training_lessons", "external_url")
    op.drop_column("training_lessons", "content_type")
    op.drop_column("training_modules", "audience_department")
    op.drop_column("training_modules", "audience_job_title")
