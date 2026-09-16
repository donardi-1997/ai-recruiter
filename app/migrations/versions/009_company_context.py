"""add versioned tenant company context

Revision ID: 009
Revises: 008
Create Date: 2026-09-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_contexts",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("owner_sub", sa.Text(), nullable=False),
        sa.Column("organization_name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="ACTIVE"),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "owner_sub",
            "version",
            name="uq_company_context_owner_version",
        ),
    )
    op.create_index(
        "idx_company_context_owner_status",
        "company_contexts",
        ["owner_sub", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_company_context_owner_status", table_name="company_contexts")
    op.drop_table("company_contexts")
