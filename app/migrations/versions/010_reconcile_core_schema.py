"""reconcile core ORM columns missing from the Alembic chain

Revision ID: 010
Revises: 009
Create Date: 2026-09-17
"""

from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    """Return the live columns for a core table during migration."""
    bind = op.get_bind()
    return {
        column["name"]
        for column in sa.inspect(bind).get_columns(table_name)
    }


def upgrade() -> None:
    """Bring the historical core schema in line with the SQLAlchemy models."""
    candidate_columns = _column_names("candidates")
    if "owner_sub" not in candidate_columns:
        op.add_column("candidates", sa.Column("owner_sub", sa.Text(), nullable=True))

    job_columns = _column_names("jobs")
    if "owner_sub" not in job_columns:
        op.add_column("jobs", sa.Column("owner_sub", sa.Text(), nullable=True))

    evaluation_columns = _column_names("evaluations")
    if "requirements" not in evaluation_columns:
        op.add_column(
            "evaluations",
            sa.Column("requirements", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    """Restore the canonical revision-009 core schema."""
    evaluation_columns = _column_names("evaluations")
    if "requirements" in evaluation_columns:
        op.drop_column("evaluations", "requirements")

    job_columns = _column_names("jobs")
    if "owner_sub" in job_columns:
        op.drop_column("jobs", "owner_sub")

    candidate_columns = _column_names("candidates")
    if "owner_sub" in candidate_columns:
        op.drop_column("candidates", "owner_sub")
