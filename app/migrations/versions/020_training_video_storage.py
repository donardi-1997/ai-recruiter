"""add managed training video metadata

Revision ID: 020
Revises: 019
Create Date: 2026-09-24
"""

from alembic import op
import sqlalchemy as sa


revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "training_lessons",
        sa.Column("video_storage_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "training_lessons",
        sa.Column("video_content_type", sa.Text(), nullable=True),
    )
    op.add_column(
        "training_lessons",
        sa.Column("video_size_bytes", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("training_lessons", "video_size_bytes")
    op.drop_column("training_lessons", "video_content_type")
    op.drop_column("training_lessons", "video_storage_key")
