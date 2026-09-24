"""Pytest configuration for app/tests/."""

import os

import pytest

# Ensure SQLite is used for all tests
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture(autouse=True)
def default_recruiter_rbac_principal():
    """Preserve the legacy test assumption that HTTP clients are recruiters.

    Production still defaults newly materialized Cognito users to EMPLOYEE.
    Existing endpoint tests historically override only get_current_user, so
    this test-only principal keeps those contracts focused on their domain
    behavior while dedicated RBAC tests cover authorization separately.
    """

    from app.access_control import PERMISSION_DEFINITIONS, SUPER_ADMIN
    from app.deps import get_current_principal
    from app.main import app

    principal = {
        "sub": "test-rbac-principal",
        "email": "test-rbac@example.com",
        "profile": {
            "id": "test-rbac-profile",
            "first_name": "Test",
            "last_name": "Recruiter",
            "job_title": "Test",
            "department": "QA",
            "status": "ACTIVE",
        },
        "roles": [SUPER_ADMIN],
        "permissions": sorted(PERMISSION_DEFINITIONS),
    }

    def override_principal():
        return principal

    app.dependency_overrides.setdefault(
        get_current_principal,
        override_principal,
    )
    try:
        yield
    finally:
        if app.dependency_overrides.get(get_current_principal) is override_principal:
            app.dependency_overrides.pop(get_current_principal, None)
