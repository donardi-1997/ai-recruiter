"""Pytest configuration for app/tests/."""

import os

import pytest
from fastapi import Depends

# Ensure SQLite is used for all tests
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture(autouse=True)
def default_recruiter_rbac_principal():
    """Preserve legacy HTTP-test identity while adding recruiter permissions.

    Production still defaults newly materialized Cognito users to EMPLOYEE.
    Existing endpoint tests historically override only get_current_user; this
    test-only dependency keeps that exact subject/email for owner-scope tests
    and adds the permissions those recruiter scenarios require.
    """

    from app.access_control import PERMISSION_DEFINITIONS, SUPER_ADMIN
    from app.deps import get_current_principal, get_current_user
    from app.main import app

    def override_principal(
        current_user: dict = Depends(get_current_user),
    ):
        return {
            "sub": current_user.get("sub"),
            "email": current_user.get("email"),
            "profile": {
                "id": f"test-profile-{current_user.get('sub')}",
                "first_name": "Test",
                "last_name": "Recruiter",
                "job_title": "Test",
                "department": "QA",
                "status": "ACTIVE",
            },
            "roles": [SUPER_ADMIN],
            "permissions": sorted(PERMISSION_DEFINITIONS),
        }

    app.dependency_overrides.setdefault(
        get_current_principal,
        override_principal,
    )
    try:
        yield
    finally:
        if app.dependency_overrides.get(get_current_principal) is override_principal:
            app.dependency_overrides.pop(get_current_principal, None)
