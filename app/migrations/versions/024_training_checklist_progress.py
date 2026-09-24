"""add persisted onboarding checklist progress

Revision ID: 024
Revises: 023
Create Date: 2026-09-24
"""

from alembic import op
import sqlalchemy as sa


revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "training_lessons",
        sa.Column("checklist_items", sa.JSON(), nullable=True),
    )
    op.add_column(
        "training_lesson_progress",
        sa.Column("details", sa.JSON(), nullable=True),
    )
    op.alter_column(
        "training_lesson_progress",
        "completed_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "training_lesson_progress",
        "completed_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.drop_column("training_lesson_progress", "details")
    op.drop_column("training_lessons", "checklist_items")
