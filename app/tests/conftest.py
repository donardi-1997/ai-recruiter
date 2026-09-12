"""Pytest configuration for app/tests/."""

import os

# Ensure SQLite is used for all tests
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
