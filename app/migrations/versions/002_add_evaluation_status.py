"""add status and error_message to evaluations

Revision ID: 002
Revises: 001
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add status column with default COMPLETED for existing rows
    op.add_column(
        "evaluations",
        sa.Column(
            "status",
            sa.Text,
            nullable=False,
            server_default="COMPLETED",
        ),
    )

    # Add error_message column (nullable, no default needed)
    op.add_column(
        "evaluations",
        sa.Column(
            "error_message",
            sa.Text,
            nullable=True,
        ),
    )

    # Backfill: mark evaluations with recommendation=EVALUATION_FAILED as FAILED
    op.execute(
        """
        UPDATE evaluations
        SET status = 'FAILED'
        WHERE recommendation = 'EVALUATION_FAILED'
        """
    )

    # Backfill: detect historical failed evaluations created before the fix
    # These have summary='Evaluacion fallida.' but recommendation='LOW_MATCH'
    op.execute(
        """
        UPDATE evaluations
        SET status = 'FAILED',
            recommendation = 'EVALUATION_FAILED'
        WHERE summary = 'Evaluacion fallida.'
        AND recommendation = 'LOW_MATCH'
        AND status = 'COMPLETED'
        """
    )


def downgrade() -> None:
    op.drop_column("evaluations", "error_message")
    op.drop_column("evaluations", "status")
