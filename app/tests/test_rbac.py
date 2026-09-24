"""Unit coverage for internal profiles and RBAC authorization."""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.access_control import (
    ADMIN,
    EMPLOYEE,
    SUPER_ADMIN,
    assign_role,
    ensure_rbac_catalog,
    resolve_principal,
)
from app.db import Base
from app.deps import require_permission, require_role
from app.models import Permission, Role, RolePermission, UserProfile, UserRole


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Role.__table__,
            Permission.__table__,
            UserProfile.__table__,
            UserRole.__table__,
            RolePermission.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_new_authenticated_user_gets_employee_role_only(db):
    principal = resolve_principal(
        db,
        {
            "sub": "cognito-user-1",
            "email": "Employee@ASIATI.com.co",
            "email_verified": "true",
        },
    )

    assert principal["email"] == "employee@asiati.com.co"
    assert principal["roles"] == [EMPLOYEE]
    assert "training.consume" in principal["permissions"]
    assert "training.quiz.take" in principal["permissions"]
    assert "employees.create" not in principal["permissions"]
    assert "candidates.restrict" not in principal["permissions"]
    assert "employee_scores.read" not in principal["permissions"]


def test_admin_can_manage_employees_but_cannot_read_private_scores(db):
    principal = resolve_principal(
        db,
        {"sub": "admin-1", "email": "admin@asiati.com.co"},
    )
    profile = db.query(UserProfile).filter_by(cognito_sub="admin-1").one()
    assign_role(db, profile, ADMIN)
    db.commit()

    principal = resolve_principal(
        db,
        {"sub": "admin-1", "email": "admin@asiati.com.co"},
    )

    assert ADMIN in principal["roles"]
    assert "employees.create" in principal["permissions"]
    assert "training.manage" in principal["permissions"]
    assert "candidates.restrict" in principal["permissions"]
    assert "employee_scores.read" not in principal["permissions"]
    assert "employee_scores.create" not in principal["permissions"]


def test_super_admin_receives_private_director_permissions(db):
    principal = resolve_principal(
        db,
        {"sub": "director-1", "email": "director@asiati.com.co"},
    )
    profile = db.query(UserProfile).filter_by(cognito_sub="director-1").one()
    assign_role(db, profile, SUPER_ADMIN)
    db.commit()

    principal = resolve_principal(
        db,
        {"sub": "director-1", "email": "director@asiati.com.co"},
    )

    assert SUPER_ADMIN in principal["roles"]
    assert "candidates.restrict" in principal["permissions"]
    assert "employee_scores.read" in principal["permissions"]
    assert "employee_scores.create" in principal["permissions"]
    assert "employee_scores.correct" in principal["permissions"]
    assert "employee_scores.export" in principal["permissions"]


def test_permission_and_role_dependencies_return_403_when_missing(db):
    employee = resolve_principal(
        db,
        {"sub": "employee-2", "email": "employee2@asiati.com.co"},
    )

    with pytest.raises(HTTPException) as permission_error:
        require_permission("employees.create")(employee)
    assert permission_error.value.status_code == 403

    with pytest.raises(HTTPException) as role_error:
        require_role(SUPER_ADMIN)(employee)
    assert role_error.value.status_code == 403


def test_rbac_catalog_is_idempotent(db):
    ensure_rbac_catalog(db)
    db.commit()
    first = (
        db.query(Role).count(),
        db.query(Permission).count(),
        db.query(RolePermission).count(),
    )

    ensure_rbac_catalog(db)
    db.commit()
    second = (
        db.query(Role).count(),
        db.query(Permission).count(),
        db.query(RolePermission).count(),
    )

    assert first == second
    assert db.query(Role).filter(Role.code == SUPER_ADMIN).one()

def test_bootstrap_admin_email_is_promoted_from_employee(db, monkeypatch):
    monkeypatch.setenv(
        "RBAC_BOOTSTRAP_ADMIN_EMAILS",
        " hr@asiati.com.co , other@asiati.com.co ",
    )

    first = resolve_principal(
        db,
        {"sub": "hr-sub", "email": "hr@asiati.com.co"},
    )
    assert first["roles"] == [ADMIN]

    profile = db.query(UserProfile).filter_by(cognito_sub="hr-sub").one()
    db.query(UserRole).filter(UserRole.user_id == profile.id).delete(
        synchronize_session=False
    )
    assign_role(db, profile, EMPLOYEE)
    db.commit()

    promoted = resolve_principal(
        db,
        {"sub": "hr-sub", "email": "hr@asiati.com.co"},
    )
    assert promoted["roles"] == [ADMIN]


def test_admin_bootstrap_never_downgrades_super_admin(db, monkeypatch):
    monkeypatch.setenv("RBAC_BOOTSTRAP_ADMIN_EMAILS", "director@asiati.com.co")

    resolve_principal(
        db,
        {"sub": "director-bootstrap", "email": "director@asiati.com.co"},
    )
    profile = db.query(UserProfile).filter_by(
        cognito_sub="director-bootstrap"
    ).one()
    db.query(UserRole).filter(UserRole.user_id == profile.id).delete(
        synchronize_session=False
    )
    assign_role(db, profile, SUPER_ADMIN)
    db.commit()

    principal = resolve_principal(
        db,
        {"sub": "director-bootstrap", "email": "director@asiati.com.co"},
    )
    assert principal["roles"] == [SUPER_ADMIN]

