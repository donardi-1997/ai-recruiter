"""add idempotent Indeed job discovery key

Revision ID: 012
Revises: 011
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "indeed_job_links",
        sa.Column("discovery_key", sa.Text(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_indeed_job_links_owner_discovery_key",
        "indeed_job_links",
        ["owner_sub", "discovery_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_indeed_job_links_owner_discovery_key",
        "indeed_job_links",
        type_="unique",
    )
    op.drop_column("indeed_job_links", "discovery_key")
