"""Employee administration tests."""

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.access_control import ADMIN, EMPLOYEE, SUPER_ADMIN, assign_role, ensure_rbac_catalog
from app.db import Base
from app.domains.employees import service
from app.domains.employees.router import (
    _enforce_assignable_role,
    _enforce_not_self,
    _enforce_target_manageable,
)
from app.models import Permission, Role, RolePermission, UserProfile, UserRole


class FakeCognitoClient:
    def __init__(self):
        self.created = []
        self.deleted = []
        self.updated = []
        self.disabled = []
        self.enabled = []

    def admin_create_user(self, **kwargs):
        self.created.append(kwargs)
        username = kwargs["Username"]
        return {
            "User": {
                "Username": username,
                "Attributes": [
                    {"Name": "sub", "Value": f"sub-{username}"},
                    {"Name": "email", "Value": username},
                ],
            }
        }

    def admin_get_user(self, **kwargs):
        username = kwargs["Username"]
        return {
            "Username": username,
            "UserAttributes": [
                {"Name": "sub", "Value": f"sub-{username}"},
                {"Name": "email", "Value": username},
            ],
        }

    def admin_delete_user(self, **kwargs):
        self.deleted.append(kwargs)

    def admin_update_user_attributes(self, **kwargs):
        self.updated.append(kwargs)

    def admin_disable_user(self, **kwargs):
        self.disabled.append(kwargs)

    def admin_enable_user(self, **kwargs):
        self.enabled.append(kwargs)


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "pool-test")
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
    ensure_rbac_catalog(session)
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _profile(db, *, email: str, role: str) -> UserProfile:
    profile = UserProfile(
        cognito_sub=f"sub-{email}",
        email=email,
        first_name="Test",
        last_name="User",
        status="ACTIVE",
    )
    db.add(profile)
    db.flush()
    assign_role(db, profile, role)
    db.commit()
    db.refresh(profile)
    return profile


def test_create_employee_provisions_cognito_and_employee_role(db):
    cognito = FakeCognitoClient()

    profile = service.create_employee(
        db,
        email=" New.Employee@ASIATI.com.co ",
        first_name="New",
        last_name="Employee",
        job_title="Comercial",
        department="Ventas",
        hire_date=date(2026, 9, 24),
        role_code=EMPLOYEE,
        created_by_sub="admin-sub",
        cognito_client=cognito,
    )

    assert profile.email == "new.employee@asiati.com.co"
    assert profile.onboarding_status == "PENDING"
    assert service.roles_for_profile(db, profile.id) == [EMPLOYEE]
    assert profile.hire_date == date(2026, 9, 24)
    assert cognito.created[0]["UserPoolId"] == "pool-test"
    assert cognito.created[0]["DesiredDeliveryMediums"] == ["EMAIL"]
    assert cognito.deleted == []




def test_create_employee_falls_back_to_admin_get_user_for_sub(db):
    class FallbackCognito(FakeCognitoClient):
        def admin_create_user(self, **kwargs):
            self.created.append(kwargs)
            return {
                "User": {
                    "Username": kwargs["Username"],
                    "Attributes": [
                        {"Name": "email", "Value": kwargs["Username"]},
                    ],
                }
            }

    cognito = FallbackCognito()

    profile = service.create_employee(
        db,
        email="fallback@asiati.com.co",
        first_name="Fallback",
        last_name="User",
        job_title=None,
        department=None,
        cognito_client=cognito,
    )

    assert profile.cognito_sub == "sub-fallback@asiati.com.co"


def test_create_employee_rejects_duplicate_profile_before_cognito(db):
    _profile(db, email="duplicate@asiati.com.co", role=EMPLOYEE)
    cognito = FakeCognitoClient()

    with pytest.raises(service.EmployeeAlreadyExists):
        service.create_employee(
            db,
            email="duplicate@asiati.com.co",
            first_name="Duplicate",
            last_name="Employee",
            job_title=None,
            department=None,
            cognito_client=cognito,
        )

    assert cognito.created == []


def test_employee_status_is_mirrored_to_cognito(db):
    employee = _profile(db, email="employee@asiati.com.co", role=EMPLOYEE)
    cognito = FakeCognitoClient()

    disabled = service.set_employee_status(
        db,
        employee.id,
        status="DISABLED",
        cognito_client=cognito,
    )
    assert disabled.status == "DISABLED"
    assert cognito.disabled[0]["Username"] == "employee@asiati.com.co"

    enabled = service.set_employee_status(
        db,
        employee.id,
        status="ACTIVE",
        cognito_client=cognito,
    )
    assert enabled.status == "ACTIVE"
    assert cognito.enabled[0]["Username"] == "employee@asiati.com.co"


def test_existing_cognito_user_can_be_materialized_for_role_bootstrap(db):
    cognito = FakeCognitoClient()

    profile = service.ensure_existing_cognito_profile(
        db,
        email="existing@asiati.com.co",
        created_by_sub="bootstrap-script",
        cognito_client=cognito,
    )

    assert profile.email == "existing@asiati.com.co"
    assert profile.cognito_sub == "sub-existing@asiati.com.co"
    assert profile.onboarding_status == "NOT_REQUIRED"
    assert service.roles_for_profile(db, profile.id) == []


def test_set_employee_role_replaces_previous_role(db):
    employee = _profile(db, email="role@asiati.com.co", role=EMPLOYEE)

    service.set_employee_role(
        db,
        employee.id,
        role_code=ADMIN,
        assigned_by_sub="director-sub",
    )

    assert service.roles_for_profile(db, employee.id) == [ADMIN]


def test_admin_can_assign_only_employee_role():
    principal = {"roles": [ADMIN], "profile": {"id": "admin-id"}}

    _enforce_assignable_role(principal, EMPLOYEE)

    with pytest.raises(HTTPException) as admin_error:
        _enforce_assignable_role(principal, ADMIN)
    assert admin_error.value.status_code == 403

    with pytest.raises(HTTPException) as super_error:
        _enforce_assignable_role(principal, SUPER_ADMIN)
    assert super_error.value.status_code == 403


def test_super_admin_can_assign_all_supported_roles():
    principal = {"roles": [SUPER_ADMIN], "profile": {"id": "director-id"}}

    _enforce_assignable_role(principal, EMPLOYEE)
    _enforce_assignable_role(principal, ADMIN)
    _enforce_assignable_role(principal, SUPER_ADMIN)


def test_admin_cannot_manage_an_administrative_target(db):
    target = _profile(db, email="other-admin@asiati.com.co", role=ADMIN)
    principal = {"roles": [ADMIN], "profile": {"id": "admin-id"}}

    with pytest.raises(HTTPException) as error:
        _enforce_target_manageable(db, principal, target.id)

    assert error.value.status_code == 403


def test_admin_can_manage_employee_target(db):
    target = _profile(db, email="worker@asiati.com.co", role=EMPLOYEE)
    principal = {"roles": [ADMIN], "profile": {"id": "admin-id"}}

    _enforce_target_manageable(db, principal, target.id)


def test_role_and_status_operations_cannot_target_self():
    principal = {"roles": [SUPER_ADMIN], "profile": {"id": "same-id"}}

    with pytest.raises(HTTPException) as error:
        _enforce_not_self(principal, "same-id")

    assert error.value.status_code == 409



def test_employee_summary_is_available_to_admin_dashboard(db):
    pending = _profile(db, email="pending@asiati.com.co", role=EMPLOYEE)
    pending.onboarding_status = "PENDING"

    in_progress = _profile(db, email="progress@asiati.com.co", role=EMPLOYEE)
    in_progress.onboarding_status = "IN_PROGRESS"

    completed = _profile(db, email="completed@asiati.com.co", role=EMPLOYEE)
    completed.onboarding_status = "COMPLETED"

    admin = _profile(db, email="admin@asiati.com.co", role=ADMIN)
    admin.onboarding_status = "NOT_REQUIRED"
    db.commit()

    summary = service.employee_summary(db)

    assert summary["employees_total"] == 4
    assert summary["active"] == 4
    assert summary["onboarding"] == {
        "total": 3,
        "pending": 1,
        "in_progress": 1,
        "completed": 1,
        "completion_percent": 33,
    }


def test_update_employee_can_change_hire_date(db):
    employee = _profile(db, email="hire-date@asiati.com.co", role=EMPLOYEE)

    updated = service.update_employee(
        db,
        employee.id,
        changes={"hire_date": date(2026, 9, 30)},
        cognito_client=FakeCognitoClient(),
    )

    assert updated.hire_date == date(2026, 9, 30)
