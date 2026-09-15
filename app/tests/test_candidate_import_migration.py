"""Contracts for safely adopting the live database into candidate-import migration 003."""

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

    assert calls == [("stamp", "002"), ("upgrade", "003")]


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


def test_revision_002_upgrades_without_stamp(monkeypatch):
    migrate = _migrate()
    calls = []
    monkeypatch.setattr(migrate, "get_current_revision", lambda: "002")
    monkeypatch.setattr(migrate, "upgrade", lambda revision: calls.append(("upgrade", revision)))
    monkeypatch.setattr(migrate, "stamp", lambda revision: calls.append(("stamp", revision)))

    migrate.ensure_candidate_import_schema()

    assert calls == [("upgrade", "003")]


def test_revision_003_is_noop(monkeypatch):
    migrate = _migrate()
    calls = []
    monkeypatch.setattr(migrate, "get_current_revision", lambda: "003")
    monkeypatch.setattr(migrate, "upgrade", lambda revision: calls.append(("upgrade", revision)))
    monkeypatch.setattr(migrate, "stamp", lambda revision: calls.append(("stamp", revision)))

    migrate.ensure_candidate_import_schema()

    assert calls == []


def test_unknown_revision_aborts_without_downgrade(monkeypatch):
    migrate = _migrate()
    calls = []
    monkeypatch.setattr(migrate, "get_current_revision", lambda: "999")
    monkeypatch.setattr(migrate, "upgrade", lambda revision: calls.append(("upgrade", revision)))
    monkeypatch.setattr(migrate, "stamp", lambda revision: calls.append(("stamp", revision)))

    with pytest.raises(RuntimeError, match="revision"):
        migrate.ensure_candidate_import_schema()

    assert calls == []


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
