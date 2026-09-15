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


def _evaluation_columns() -> set[str]:
    """Return the columns present when this historical migration runs.

    Revision 001 was later amended to include ``status`` and ``error_message``.
    Older databases may still have the original 001 schema without those
    columns, while fresh databases built from the current repository already
    contain them. Keep 002 forward-compatible with both states.
    """

    bind = op.get_bind()
    return {column["name"] for column in sa.inspect(bind).get_columns("evaluations")}


def upgrade() -> None:
    columns = _evaluation_columns()

    # Add status only for databases created from the original revision 001.
    if "status" not in columns:
        op.add_column(
            "evaluations",
            sa.Column(
                "status",
                sa.Text,
                nullable=False,
                server_default="COMPLETED",
            ),
        )

    # Add error_message only for databases created from the original revision 001.
    if "error_message" not in columns:
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
