"""add training quizzes and attempts

Revision ID: 019
Revises: 018
Create Date: 2026-09-24
"""

from alembic import op
import sqlalchemy as sa


revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_quizzes",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("course_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("passing_score", sa.Integer(), nullable=False, server_default="70"),
        sa.Column("created_by_sub", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["training_courses.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", name="uq_training_quizzes_course"),
    )

    op.create_table(
        "training_quiz_questions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("quiz_id", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("correct_option", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["quiz_id"],
            ["training_quizzes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "quiz_id",
            "position",
            name="uq_training_quiz_questions_quiz_position",
        ),
    )

    op.create_table(
        "training_quiz_attempts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("assignment_id", sa.Text(), nullable=False),
        sa.Column("quiz_id", sa.Text(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("score_percent", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["training_assignments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["quiz_id"],
            ["training_quizzes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assignment_id",
            "attempt_number",
            name="uq_training_quiz_attempts_assignment_number",
        ),
    )
    op.create_index(
        "idx_training_quiz_attempts_assignment_submitted",
        "training_quiz_attempts",
        ["assignment_id", "submitted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_training_quiz_attempts_assignment_submitted",
        table_name="training_quiz_attempts",
    )
    op.drop_table("training_quiz_attempts")
    op.drop_table("training_quiz_questions")
    op.drop_table("training_quizzes")
