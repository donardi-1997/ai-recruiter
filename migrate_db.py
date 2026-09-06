#!/usr/bin/env python3
"""Database migration script for AI Recruiter.

Adds status and error_message columns to evaluations table.
Run this on the production server AFTER deploying the new code.

Usage:
    python migrate_db.py

This script is idempotent - it checks if columns exist before adding them.
"""

import os
import sys

import psycopg2
from psycopg2 import sql


def get_connection():
    """Get database connection from environment."""
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/ai_recruiter",
    )
    return psycopg2.connect(database_url)


def column_exists(conn, table_name, column_name):
    """Check if a column exists in a table."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = %s
                AND column_name = %s
            )
            """,
            (table_name, column_name),
        )
        return cur.fetchone()[0]


def get_evaluation_counts(conn):
    """Get counts of evaluations by recommendation and status."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                recommendation,
                status,
                COUNT(*)
            FROM evaluations
            GROUP BY recommendation, status
            ORDER BY recommendation, status
            """
        )
        return cur.fetchall()


def migrate():
    """Run the migration."""
    print("Connecting to database...")
    conn = get_connection()
    conn.autocommit = False

    try:
        # Check if columns exist
        has_status = column_exists(conn, "evaluations", "status")
        has_error_message = column_exists(conn, "evaluations", "error_message")

        print(f"Column 'status' exists: {has_status}")
        print(f"Column 'error_message' exists: {has_error_message}")

        if has_status and has_error_message:
            print("Migration already applied. No changes needed.")
            return

        # Show current state
        print("\nCurrent evaluation counts (before migration):")
        counts = get_evaluation_counts(conn)
        for rec, status, count in counts:
            print(f"  recommendation={rec}, status={status}: {count}")

        # Add columns
        with conn.cursor() as cur:
            if not has_status:
                print("\nAdding 'status' column...")
                cur.execute(
                    """
                    ALTER TABLE evaluations
                    ADD COLUMN status TEXT NOT NULL DEFAULT 'COMPLETED'
                    """
                )
                print("  Added 'status' column with default 'COMPLETED'")

            if not has_error_message:
                print("\nAdding 'error_message' column...")
                cur.execute(
                    """
                    ALTER TABLE evaluations
                    ADD COLUMN error_message TEXT
                    """
                )
                print("  Added 'error_message' column (nullable)")

            # Backfill: mark evaluations with recommendation=EVALUATION_FAILED as FAILED
            print("\nBackfilling status for EVALUATION_FAILED recommendations...")
            cur.execute(
                """
                UPDATE evaluations
                SET status = 'FAILED'
                WHERE recommendation = 'EVALUATION_FAILED'
                """
            )
            failed_count = cur.rowcount
            print(f"  Updated {failed_count} rows with EVALUATION_FAILED -> FAILED")

            # Backfill: detect historical failed evaluations
            # These have summary='Evaluacion fallida.' but recommendation='LOW_MATCH'
            print("\nBackfilling historical failed evaluations...")
            cur.execute(
                """
                UPDATE evaluations
                SET status = 'FAILED',
                    recommendation = 'EVALUATION_FAILED'
                WHERE summary = 'Evaluacion fallida.'
                AND recommendation = 'LOW_MATCH'
                AND status = 'COMPLETED'
                """
            )
            historical_count = cur.rowcount
            print(f"  Updated {historical_count} historical failed evaluations")

        # Commit
        conn.commit()
        print("\nMigration committed successfully!")

        # Show final state
        print("\nFinal evaluation counts (after migration):")
        counts = get_evaluation_counts(conn)
        for rec, status, count in counts:
            print(f"  recommendation={rec}, status={status}: {count}")

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: Migration failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
