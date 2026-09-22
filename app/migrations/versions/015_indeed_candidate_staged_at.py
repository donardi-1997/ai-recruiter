"""track Indeed application staged time

Revision ID: 015
Revises: 014
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa


revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "indeed_candidate_links",
        sa.Column("staged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_indeed_candidate_links_owner_job_candidate_staged",
        "indeed_candidate_links",
        ["owner_sub", "job_id", "candidate_id", "staged_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_indeed_candidate_links_owner_job_candidate_staged",
        table_name="indeed_candidate_links",
    )
    op.drop_column("indeed_candidate_links", "staged_at")
