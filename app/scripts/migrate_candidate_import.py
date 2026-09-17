"""Safely adopt the legacy production baseline and upgrade Alembic to head."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import inspect

from app.db import get_engine

BASELINE_REVISION = "002"
TARGET_REVISION = "head"
REQUIRED_BASELINE_COLUMNS = {
    "candidates": {"owner_sub"},
    "jobs": {"owner_sub"},
    "evaluations": {"requirements"},
}


def _alembic_config() -> Config:
    """Build an Alembic config whose migration path is independent of cwd."""
    app_dir = Path(__file__).resolve().parents[1]
    config = Config(str(app_dir / "alembic.ini"))
    config.set_main_option("script_location", str(app_dir / "migrations"))
    return config


def get_current_revision() -> str | None:
    """Return the live Alembic revision, or None when the DB is unstamped."""
    with get_engine().connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def database_has_current_baseline() -> bool:
    """Recognize only the known live schema that corresponds to revision 002."""
    inspector = inspect(get_engine())
    tables = set(inspector.get_table_names())

    for table_name, required_columns in REQUIRED_BASELINE_COLUMNS.items():
        if table_name not in tables:
            return False
        actual_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        if not required_columns.issubset(actual_columns):
            return False
    return True


def revision_is_known(revision: str) -> bool:
    """Return whether the revision exists in the migration graph shipped with the app."""
    scripts = ScriptDirectory.from_config(_alembic_config())
    try:
        scripts.get_revision(revision)
    except CommandError:
        return False
    return True


def stamp(revision: str) -> None:
    """Stamp a verified pre-Alembic live baseline without running old DDL."""
    command.stamp(_alembic_config(), revision)


def upgrade(revision: str) -> None:
    """Upgrade the configured database to the requested Alembic revision."""
    command.upgrade(_alembic_config(), revision)


def ensure_candidate_import_schema() -> None:
    """Adopt the known legacy baseline when needed and otherwise migrate to head."""
    current = get_current_revision()

    if current is None:
        if not database_has_current_baseline():
            raise RuntimeError(
                "Unrecognized database baseline; refusing to stamp migration 002."
            )
        stamp(BASELINE_REVISION)
    elif not revision_is_known(current):
        raise RuntimeError(
            f"Unsupported Alembic revision {current!r}; refusing automatic migration."
        )

    upgrade(TARGET_REVISION)


def main() -> None:
    ensure_candidate_import_schema()


if __name__ == "__main__":
    main()
