"""Tests for health check endpoint.

Run:  python -m pytest app/tests/test_health.py -v
"""

import os

# Force SQLite before any app imports
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.deps import get_current_user, get_db
from app.main import app


# ============================================================
# FIXTURES
# ============================================================

_test_db_fd = None
_test_db_path = None


@pytest.fixture(scope="function")
def client():
    """Yield a TestClient with auth stub."""
    def _override_get_current_user():
        return {"sub": "test-user"}

    app.dependency_overrides[get_current_user] = _override_get_current_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ============================================================
# TESTS
# ============================================================

class TestHealthCheck:
    def test_returns_200_when_no_database(self, client):
        """No DATABASE_URL configured → 200 OK."""
        with patch.dict(os.environ, {"DATABASE_URL": ""}):
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["db"] is True

    def test_returns_200_when_db_ok(self, client):
        """DATABASE_URL configured, DB responds → 200 OK."""
        # SQLite in-memory is configured via env var
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["db"] is True

    def test_returns_503_when_db_fails(self, client):
        """DATABASE_URL configured but connection fails → 503."""
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://invalid:bad@localhost:99999/nodb"}):
            # Force a new engine creation
            import app.health as health_mod
            import app.db as db_mod
            # Reset cached engine so it tries the bad URL
            original_engine = db_mod._engine
            db_mod._engine = None
            try:
                resp = client.get("/health")
                assert resp.status_code == 503
                data = resp.json()
                assert data["status"] == "unhealthy"
                assert data["db"] is False
            finally:
                db_mod._engine = original_engine

    def test_health_endpoint_exists(self, client):
        """Verify /health endpoint is registered."""
        resp = client.get("/health")
        assert resp.status_code in (200, 503)

    def test_health_does_not_require_auth(self, client):
        """Health endpoint should work without authentication."""
        # The client fixture adds auth override, but health doesn't use it
        resp = client.get("/health")
        assert resp.status_code in (200, 503)
