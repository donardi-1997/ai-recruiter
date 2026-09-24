"""add training courses assignments and progress

Revision ID: 018
Revises: 017
Create Date: 2026-09-24
"""

from alembic import op
import sqlalchemy as sa


revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_courses",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="DRAFT"),
        sa.Column("created_by_sub", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_training_courses_status",
        "training_courses",
        ["status"],
        unique=False,
    )

    op.create_table(
        "training_modules",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("course_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
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
        sa.UniqueConstraint(
            "course_id",
            "position",
            name="uq_training_modules_course_position",
        ),
    )

    op.create_table(
        "training_lessons",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("module_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("video_url", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["training_modules.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "module_id",
            "position",
            name="uq_training_lessons_module_position",
        ),
    )

    op.create_table(
        "training_assignments",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("course_id", sa.Text(), nullable=False),
        sa.Column("employee_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="ASSIGNED"),
        sa.Column("assigned_by_sub", sa.Text(), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["training_courses.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["user_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "course_id",
            "employee_id",
            name="uq_training_assignments_course_employee",
        ),
    )
    op.create_index(
        "idx_training_assignments_employee_status",
        "training_assignments",
        ["employee_id", "status"],
        unique=False,
    )

    op.create_table(
        "training_lesson_progress",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("assignment_id", sa.Text(), nullable=False),
        sa.Column("lesson_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="COMPLETED"),
        sa.Column(
            "completed_at",
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
            ["lesson_id"],
            ["training_lessons.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assignment_id",
            "lesson_id",
            name="uq_training_lesson_progress_assignment_lesson",
        ),
    )
    op.create_index(
        "idx_training_lesson_progress_assignment_status",
        "training_lesson_progress",
        ["assignment_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_training_lesson_progress_assignment_status",
        table_name="training_lesson_progress",
    )
    op.drop_table("training_lesson_progress")
    op.drop_index(
        "idx_training_assignments_employee_status",
        table_name="training_assignments",
    )
    op.drop_table("training_assignments")
    op.drop_table("training_lessons")
    op.drop_table("training_modules")
    op.drop_index("idx_training_courses_status", table_name="training_courses")
    op.drop_table("training_courses")
