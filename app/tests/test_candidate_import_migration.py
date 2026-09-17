"""Contracts for safely adopting production and migrating Alembic to head."""

import importlib

import pytest


def _migrate():
    return importlib.import_module("app.scripts.migrate_candidate_import")


def test_existing_schema_without_alembic_version_is_stamped_then_upgraded(monkeypatch):
    migrate = _migrate()
    calls = []
    monkeypatch.setattr(migrate, "database_has_current_baseline", lambda: True)
    monkeypatch.setattr(migrate, "get_current_revision", lambda: None)
    monkeypatch.setattr(migrate, "stamp", lambda revision: calls.append(("stamp", revision)))
    monkeypatch.setattr(migrate, "upgrade", lambda revision: calls.append(("upgrade", revision)))

    migrate.ensure_candidate_import_schema()

    assert calls == [("stamp", "002"), ("upgrade", "head")]


def test_unknown_or_incomplete_baseline_aborts_without_stamp(monkeypatch):
    migrate = _migrate()
    calls = []
    monkeypatch.setattr(migrate, "database_has_current_baseline", lambda: False)
    monkeypatch.setattr(migrate, "get_current_revision", lambda: None)
    monkeypatch.setattr(migrate, "stamp", lambda revision: calls.append(("stamp", revision)))
    monkeypatch.setattr(migrate, "upgrade", lambda revision: calls.append(("upgrade", revision)))

    with pytest.raises(RuntimeError, match="baseline"):
        migrate.ensure_candidate_import_schema()

    assert calls == []


@pytest.mark.parametrize("revision", ["002", "003", "009"])
def test_known_revision_upgrades_to_head_without_stamp(monkeypatch, revision):
    migrate = _migrate()
    calls = []
    monkeypatch.setattr(migrate, "get_current_revision", lambda: revision)
    monkeypatch.setattr(migrate, "upgrade", lambda target: calls.append(("upgrade", target)))
    monkeypatch.setattr(migrate, "stamp", lambda target: calls.append(("stamp", target)))

    migrate.ensure_candidate_import_schema()

    assert calls == [("upgrade", "head")]


def test_unknown_revision_aborts_without_upgrade_or_stamp(monkeypatch):
    migrate = _migrate()
    calls = []
    monkeypatch.setattr(migrate, "get_current_revision", lambda: "999")
    monkeypatch.setattr(migrate, "upgrade", lambda revision: calls.append(("upgrade", revision)))
    monkeypatch.setattr(migrate, "stamp", lambda revision: calls.append(("stamp", revision)))

    with pytest.raises(RuntimeError, match="revision"):
        migrate.ensure_candidate_import_schema()

    assert calls == []


def test_revision_validation_uses_shipped_migration_graph():
    migrate = _migrate()

    assert migrate.revision_is_known("002") is True
    assert migrate.revision_is_known("009") is True
    assert migrate.revision_is_known("999") is False


def test_baseline_inspection_requires_owner_and_requirements_columns(monkeypatch):
    migrate = _migrate()

    class Inspector:
        def __init__(self, columns):
            self.columns = columns

        def get_table_names(self):
            return list(self.columns)

        def get_columns(self, table_name):
            return [{"name": name} for name in self.columns[table_name]]

    complete = {
        "candidates": {"id", "owner_sub"},
        "jobs": {"id", "owner_sub"},
        "evaluations": {"id", "requirements"},
    }
    monkeypatch.setattr(migrate, "inspect", lambda engine: Inspector(complete))
    monkeypatch.setattr(migrate, "get_engine", lambda: object())
    assert migrate.database_has_current_baseline() is True

    incomplete = {
        "candidates": {"id", "owner_sub"},
        "jobs": {"id", "owner_sub"},
        "evaluations": {"id"},
    }
    monkeypatch.setattr(migrate, "inspect", lambda engine: Inspector(incomplete))
    assert migrate.database_has_current_baseline() is False
