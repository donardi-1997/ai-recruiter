"""Employee administration service."""

from __future__ import annotations

import os

from botocore.exceptions import ClientError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.access_control import EMPLOYEE, assign_role, normalize_email
from app.infrastructure.auth.cognito import get_admin_cognito_client
from app.models import UserProfile, UserRole


class EmployeeNotFound(Exception):
    pass


class EmployeeAlreadyExists(Exception):
    pass


class EmployeeIdentityError(Exception):
    pass


class EmployeeProvisioningError(Exception):
    pass


class EmployeeStateError(Exception):
    pass


def _user_pool_id() -> str:
    value = os.getenv("COGNITO_USER_POOL_ID", "").strip()
    if not value:
        raise EmployeeProvisioningError("COGNITO_USER_POOL_ID is not configured")
    return value


def roles_for_profile(db: Session, profile_id: str) -> list[str]:
    return sorted(
        role_code
        for (role_code,) in (
            db.query(UserRole.role_code)
            .filter(UserRole.user_id == profile_id)
            .all()
        )
    )


def employee_payload(db: Session, profile: UserProfile) -> dict:
    return {
        "id": profile.id,
        "cognito_sub": profile.cognito_sub,
        "email": profile.email,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "job_title": profile.job_title,
        "department": profile.department,
        "status": profile.status,
        "roles": roles_for_profile(db, profile.id),
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def require_employee(db: Session, employee_id: str) -> UserProfile:
    profile = db.query(UserProfile).filter(UserProfile.id == employee_id).one_or_none()
    if profile is None:
        raise EmployeeNotFound()
    return profile


def list_employees(
    db: Session,
    *,
    q: str = "",
    status: str | None = None,
) -> list[UserProfile]:
    query = db.query(UserProfile)
    normalized_q = q.strip()
    if normalized_q:
        pattern = f"%{normalized_q}%"
        query = query.filter(
            or_(
                UserProfile.email.ilike(pattern),
                UserProfile.first_name.ilike(pattern),
                UserProfile.last_name.ilike(pattern),
                UserProfile.job_title.ilike(pattern),
                UserProfile.department.ilike(pattern),
            )
        )
    if status:
        query = query.filter(UserProfile.status == status)
    return query.order_by(UserProfile.first_name.asc(), UserProfile.last_name.asc()).all()


def _cognito_sub_from_user(user: dict) -> str:
    raw_attrs = user.get("Attributes") or user.get("UserAttributes") or []
    attrs = {
        item.get("Name"): item.get("Value")
        for item in raw_attrs
        if item.get("Name")
    }
    return str(attrs.get("sub") or "").strip()


def create_employee(
    db: Session,
    *,
    email: str,
    first_name: str,
    last_name: str,
    job_title: str | None,
    department: str | None,
    role_code: str = EMPLOYEE,
    created_by_sub: str | None = None,
    cognito_client=None,
) -> UserProfile:
    email = normalize_email(email)
    if db.query(UserProfile).filter(UserProfile.email == email).first() is not None:
        raise EmployeeAlreadyExists()

    client = cognito_client or get_admin_cognito_client()
    pool_id = _user_pool_id()
    cognito_created = False

    try:
        response = client.admin_create_user(
            UserPoolId=pool_id,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "given_name", "Value": first_name},
                {"Name": "family_name", "Value": last_name},
            ],
            DesiredDeliveryMediums=["EMAIL"],
        )
        cognito_created = True
        user = response.get("User") or {}
        sub = _cognito_sub_from_user(user)
        if not sub:
            user = client.admin_get_user(UserPoolId=pool_id, Username=email)
            sub = _cognito_sub_from_user(user)
        if not sub:
            raise EmployeeIdentityError("Cognito did not return a stable subject")

        profile = UserProfile(
            cognito_sub=sub,
            email=email,
            first_name=first_name,
            last_name=last_name,
            job_title=job_title,
            department=department,
            status="ACTIVE",
            created_by_sub=created_by_sub,
        )
        db.add(profile)
        db.flush()
        assign_role(
            db,
            profile,
            role_code,
            assigned_by_sub=created_by_sub,
        )
        db.commit()
        db.refresh(profile)
        return profile
    except ClientError as exc:
        db.rollback()
        code = str(exc.response.get("Error", {}).get("Code") or "")
        if cognito_created:
            try:
                client.admin_delete_user(UserPoolId=pool_id, Username=email)
            except Exception:
                pass
        if code == "UsernameExistsException":
            raise EmployeeAlreadyExists() from exc
        raise EmployeeProvisioningError(code or "Cognito error") from exc
    except Exception:
        db.rollback()
        if cognito_created:
            try:
                client.admin_delete_user(UserPoolId=pool_id, Username=email)
            except Exception:
                pass
        raise


def update_employee(
    db: Session,
    employee_id: str,
    *,
    changes: dict,
    cognito_client=None,
) -> UserProfile:
    profile = require_employee(db, employee_id)
    allowed = {"first_name", "last_name", "job_title", "department"}
    changes = {key: value for key, value in changes.items() if key in allowed}

    identity_changes = []
    if "first_name" in changes and changes["first_name"]:
        identity_changes.append({"Name": "given_name", "Value": changes["first_name"]})
    if "last_name" in changes and changes["last_name"]:
        identity_changes.append({"Name": "family_name", "Value": changes["last_name"]})

    if identity_changes:
        client = cognito_client or get_admin_cognito_client()
        try:
            client.admin_update_user_attributes(
                UserPoolId=_user_pool_id(),
                Username=profile.email,
                UserAttributes=identity_changes,
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code") or "")
            raise EmployeeProvisioningError(code or "Cognito error") from exc

    for key, value in changes.items():
        setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


def set_employee_status(
    db: Session,
    employee_id: str,
    *,
    status: str,
    cognito_client=None,
) -> UserProfile:
    profile = require_employee(db, employee_id)
    if status not in {"ACTIVE", "DISABLED"}:
        raise EmployeeStateError()

    client = cognito_client or get_admin_cognito_client()
    try:
        if status == "ACTIVE":
            client.admin_enable_user(
                UserPoolId=_user_pool_id(),
                Username=profile.email,
            )
        else:
            client.admin_disable_user(
                UserPoolId=_user_pool_id(),
                Username=profile.email,
            )
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code") or "")
        raise EmployeeProvisioningError(code or "Cognito error") from exc

    profile.status = status
    db.commit()
    db.refresh(profile)
    return profile


def set_employee_role(
    db: Session,
    employee_id: str,
    *,
    role_code: str,
    assigned_by_sub: str | None,
) -> UserProfile:
    profile = require_employee(db, employee_id)
    db.query(UserRole).filter(UserRole.user_id == profile.id).delete(
        synchronize_session=False
    )
    assign_role(
        db,
        profile,
        role_code,
        assigned_by_sub=assigned_by_sub,
    )
    db.commit()
    db.refresh(profile)
    return profile
