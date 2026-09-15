"""
Idempotent PostgreSQL migration for:
- jobs.owner_sub
- candidates.owner_sub
- evaluations.requirements

Usage:

CHECK ONLY:
    python scripts/migrate_owner_requirements.py --check

MIGRATE LEGACY DATA:
    LEGACY_OWNER_SUB=<cognito-sub> \
    python scripts/migrate_owner_requirements.py
"""

import argparse
import os

from sqlalchemy import create_engine, text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
    )
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL no está definido."
        )

    if not database_url.startswith(
        ("postgresql://", "postgresql+")
    ):
        raise RuntimeError(
            "Esta migración es solo para PostgreSQL."
        )

    engine = create_engine(database_url)

    if args.check:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT
                        table_name,
                        column_name,
                        data_type,
                        is_nullable
                    FROM information_schema.columns
                    WHERE
                        table_schema = 'public'
                        AND (
                            (
                                table_name IN (
                                    'jobs',
                                    'candidates'
                                )
                                AND column_name = 'owner_sub'
                            )
                            OR (
                                table_name = 'evaluations'
                                AND column_name = 'requirements'
                            )
                        )
                    ORDER BY table_name, column_name
                """)
            ).mappings().all()

            print("COLUMNAS:")
            for row in rows:
                print(dict(row))

            for table_name in (
                "jobs",
                "candidates",
            ):
                try:
                    count = conn.execute(
                        text(
                            f"""
                            SELECT COUNT(*)
                            FROM {table_name}
                            WHERE owner_sub IS NULL
                            """
                        )
                    ).scalar_one()

                    print(
                        f"{table_name} sin owner: {count}"
                    )
                except Exception:
                    print(
                        f"{table_name}.owner_sub "
                        "todavía no existe"
                    )

        return

    legacy_owner_sub = os.getenv(
        "LEGACY_OWNER_SUB"
    )

    with engine.begin() as conn:

        conn.execute(
            text("""
                ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS
                owner_sub TEXT
            """)
        )

        conn.execute(
            text("""
                ALTER TABLE candidates
                ADD COLUMN IF NOT EXISTS
                owner_sub TEXT
            """)
        )

        conn.execute(
            text("""
                ALTER TABLE evaluations
                ADD COLUMN IF NOT EXISTS
                requirements JSONB
            """)
        )

        conn.execute(
            text("""
                UPDATE evaluations
                SET requirements = '[]'::jsonb
                WHERE requirements IS NULL
            """)
        )

        jobs_missing = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM jobs
                WHERE owner_sub IS NULL
            """)
        ).scalar_one()

        candidates_missing = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM candidates
                WHERE owner_sub IS NULL
            """)
        ).scalar_one()

        if (
            jobs_missing > 0
            or candidates_missing > 0
        ) and not legacy_owner_sub:
            raise RuntimeError(
                "Hay datos legacy sin propietario. "
                "Define LEGACY_OWNER_SUB con el "
                "sub real de Cognito antes de migrar. "
                f"jobs={jobs_missing}, "
                f"candidates={candidates_missing}"
            )

        if legacy_owner_sub:
            conn.execute(
                text("""
                    UPDATE jobs
                    SET owner_sub = :owner
                    WHERE owner_sub IS NULL
                """),
                {"owner": legacy_owner_sub},
            )

            conn.execute(
                text("""
                    UPDATE candidates
                    SET owner_sub = :owner
                    WHERE owner_sub IS NULL
                """),
                {"owner": legacy_owner_sub},
            )

        remaining_jobs = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM jobs
                WHERE owner_sub IS NULL
            """)
        ).scalar_one()

        remaining_candidates = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM candidates
                WHERE owner_sub IS NULL
            """)
        ).scalar_one()

        if (
            remaining_jobs
            or remaining_candidates
        ):
            raise RuntimeError(
                "No se puede aplicar NOT NULL: "
                "todavía existen datos sin owner."
            )

        conn.execute(
            text("""
                ALTER TABLE jobs
                ALTER COLUMN owner_sub
                SET NOT NULL
            """)
        )

        conn.execute(
            text("""
                ALTER TABLE candidates
                ALTER COLUMN owner_sub
                SET NOT NULL
            """)
        )

        conn.execute(
            text("""
                ALTER TABLE evaluations
                ALTER COLUMN requirements
                SET DEFAULT '[]'::jsonb
            """)
        )

        conn.execute(
            text("""
                ALTER TABLE evaluations
                ALTER COLUMN requirements
                SET NOT NULL
            """)
        )

        conn.execute(
            text("""
                CREATE INDEX IF NOT EXISTS
                ix_jobs_owner_sub
                ON jobs(owner_sub)
            """)
        )

        conn.execute(
            text("""
                CREATE INDEX IF NOT EXISTS
                ix_candidates_owner_sub
                ON candidates(owner_sub)
            """)
        )

    print(
        "OK - migration ownership/requirements applied"
    )


if __name__ == "__main__":
    main()
