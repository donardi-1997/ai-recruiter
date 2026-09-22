"""enforce logical uniqueness for assignments and evaluations

Revision ID: 013
Revises: 012
Create Date: 2026-09-22
"""

from alembic import op


revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve the most recent application state if historical races produced
    # duplicate candidate/job assignments before the DB constraint existed.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY job_id, candidate_id
                    ORDER BY status_changed_at DESC NULLS LAST,
                             assigned_at DESC NULLS LAST,
                             id DESC
                ) AS rn
            FROM job_candidates
        )
        DELETE FROM job_candidates AS target
        USING ranked
        WHERE target.id = ranked.id
          AND ranked.rn > 1
        """
    )

    # Evaluations are mutable upserts in the application model, not an audit
    # history. Retain only the latest row per logical candidate/job pair.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY job_id, candidate_id
                    ORDER BY created_at DESC NULLS LAST, id DESC
                ) AS rn
            FROM evaluations
        )
        DELETE FROM evaluations AS target
        USING ranked
        WHERE target.id = ranked.id
          AND ranked.rn > 1
        """
    )

    op.create_unique_constraint(
        "uq_job_candidates_job_candidate",
        "job_candidates",
        ["job_id", "candidate_id"],
    )
    op.create_unique_constraint(
        "uq_evaluations_job_candidate",
        "evaluations",
        ["job_id", "candidate_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_evaluations_job_candidate",
        "evaluations",
        type_="unique",
    )
    op.drop_constraint(
        "uq_job_candidates_job_candidate",
        "job_candidates",
        type_="unique",
    )
