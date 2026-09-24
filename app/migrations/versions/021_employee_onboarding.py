"""add employee onboarding lifecycle

Revision ID: 021
Revises: 020
Create Date: 2026-09-24
"""

from alembic import op
import sqlalchemy as sa


revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("hire_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "user_profiles",
        sa.Column(
            "onboarding_status",
            sa.Text(),
            nullable=False,
            server_default="NOT_REQUIRED",
        ),
    )
    op.add_column(
        "user_profiles",
        sa.Column("onboarding_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_profiles",
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "training_courses",
        sa.Column(
            "is_onboarding",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("training_courses", "is_onboarding")
    op.drop_column("user_profiles", "onboarding_completed_at")
    op.drop_column("user_profiles", "onboarding_started_at")
    op.drop_column("user_profiles", "onboarding_status")
    op.drop_column("user_profiles", "hire_date")
