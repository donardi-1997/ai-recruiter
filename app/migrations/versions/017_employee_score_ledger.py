"""add private employee score ledger

Revision ID: 017
Revises: 016
Create Date: 2026-09-24
"""

from alembic import op
import sqlalchemy as sa


revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employee_score_events",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("employee_id", sa.Text(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "event_date",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_sub", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by_sub", sa.Text(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "points <> 0",
            name="ck_employee_score_events_nonzero_points",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["user_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_employee_score_events_employee_status_date",
        "employee_score_events",
        ["employee_id", "status", "event_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_employee_score_events_employee_status_date",
        table_name="employee_score_events",
    )
    op.drop_table("employee_score_events")
