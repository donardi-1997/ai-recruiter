"""Employee administration HTTP routes."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.access_control import EMPLOYEE, SUPER_ADMIN
from app.deps import get_db, require_permission
from app.domains.employees import service
from app.domains.training import service as training_service
from app.domains.employees.schemas import (
    CreateEmployeeRequest,
    SetEmployeeRoleRequest,
    SetEmployeeStatusRequest,
    UpdateEmployeeRequest,
)


router = APIRouter(prefix="/api/employees", tags=["employees"])
logger = logging.getLogger(__name__)


def _is_super_admin(principal: dict) -> bool:
    return SUPER_ADMIN in set(principal.get("roles") or [])


def _enforce_assignable_role(principal: dict, role_code: str) -> None:
    if role_code == EMPLOYEE:
        return
    if not _is_super_admin(principal):
        raise HTTPException(
            status_code=403,
            detail="Solo Direccion puede asignar roles administrativos.",
        )


def _enforce_not_self(principal: dict, employee_id: str) -> None:
    profile = principal.get("profile") or {}
    if profile.get("id") == employee_id:
        raise HTTPException(
            status_code=409,
            detail="No puedes modificar tu propio rol o estado desde esta operacion.",
        )

def _enforce_target_manageable(
    db: Session,
    principal: dict,
    employee_id: str,
) -> None:
    if _is_super_admin(principal):
        return
    employee = service.require_employee(db, employee_id)
    target_roles = set(service.roles_for_profile(db, employee.id))
    if target_roles - {EMPLOYEE}:
        raise HTTPException(
            status_code=403,
            detail="Solo Direccion puede administrar perfiles administrativos.",
        )



def _translate_service_error(exc: Exception):
    if isinstance(exc, service.EmployeeNotFound):
        raise HTTPException(status_code=404, detail="Empleado no encontrado.")
    if isinstance(exc, service.EmployeeAlreadyExists):
        raise HTTPException(
            status_code=409,
            detail="Ya existe un usuario con este correo.",
        )
    if isinstance(exc, service.EmployeeStateError):
        raise HTTPException(status_code=422, detail="Estado de empleado no valido.")
    if isinstance(exc, service.EmployeeIdentityError):
        raise HTTPException(
            status_code=502,
            detail="Cognito no devolvio una identidad valida para el empleado.",
        )
    if isinstance(exc, service.EmployeeProvisioningError):
        raise HTTPException(
            status_code=502,
            detail="No fue posible sincronizar el empleado con Cognito.",
        )
    raise exc


@router.get("")
def list_employees(
    q: str = Query("", max_length=120),
    status: Literal["ACTIVE", "DISABLED"] | None = Query(None),
    db: Session = Depends(get_db),
    _principal: dict = Depends(require_permission("employees.read")),
):
    employees = service.list_employees(db, q=q, status=status)
    return {
        "items": [service.employee_payload(db, employee) for employee in employees],
        "total": len(employees),
    }


@router.get("/summary")
def get_employee_summary(
    db: Session = Depends(get_db),
    _principal: dict = Depends(require_permission("employees.read")),
):
    return service.employee_summary(db)


@router.get("/{employee_id}")
def get_employee(
    employee_id: str,
    db: Session = Depends(get_db),
    _principal: dict = Depends(require_permission("employees.read")),
):
    try:
        employee = service.require_employee(db, employee_id)
        return service.employee_payload(db, employee)
    except Exception as exc:
        _translate_service_error(exc)


@router.post("", status_code=201)
def create_employee(
    body: CreateEmployeeRequest,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("employees.create")),
):
    _enforce_assignable_role(principal, body.role)
    try:
        employee = service.create_employee(
            db,
            email=body.email,
            first_name=body.first_name,
            last_name=body.last_name,
            job_title=body.job_title,
            department=body.department,
            hire_date=body.hire_date,
            role_code=body.role,
            created_by_sub=principal.get("sub"),
        )

        onboarding_assignments = []
        onboarding_warning = None
        if body.role == EMPLOYEE and body.assign_onboarding:
            try:
                onboarding_assignments = (
                    training_service.assign_published_onboarding_courses(
                        db,
                        employee_id=employee.id,
                        assigned_by_sub=principal.get("sub") or employee.cognito_sub,
                    )
                )
            except Exception:
                logger.exception(
                    "Employee %s was created but automatic onboarding assignment failed.",
                    employee.id,
                )
                onboarding_warning = (
                    "El empleado fue creado, pero no fue posible asignar "
                    "automáticamente la capacitación de onboarding."
                )

        payload = service.employee_payload(db, employee)
        payload["onboarding_assigned_count"] = len(onboarding_assignments)
        payload["onboarding_assignment_warning"] = onboarding_warning
        return payload
    except Exception as exc:
        _translate_service_error(exc)


@router.put("/{employee_id}")
def update_employee(
    employee_id: str,
    body: UpdateEmployeeRequest,
    db: Session = Depends(get_db),
    _principal: dict = Depends(require_permission("employees.update")),
):
    try:
        _enforce_target_manageable(db, _principal, employee_id)
        employee = service.update_employee(
            db,
            employee_id,
            changes=body.model_dump(exclude_unset=True),
        )
        return service.employee_payload(db, employee)
    except Exception as exc:
        _translate_service_error(exc)


@router.put("/{employee_id}/status")
def update_employee_status(
    employee_id: str,
    body: SetEmployeeStatusRequest,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("employees.disable")),
):
    _enforce_not_self(principal, employee_id)
    try:
        _enforce_target_manageable(db, principal, employee_id)
        employee = service.set_employee_status(
            db,
            employee_id,
            status=body.status,
        )
        return service.employee_payload(db, employee)
    except Exception as exc:
        _translate_service_error(exc)


@router.put("/{employee_id}/role")
def update_employee_role(
    employee_id: str,
    body: SetEmployeeRoleRequest,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("employees.roles.manage")),
):
    _enforce_not_self(principal, employee_id)
    _enforce_assignable_role(principal, body.role)
    try:
        _enforce_target_manageable(db, principal, employee_id)
        employee = service.set_employee_role(
            db,
            employee_id,
            role_code=body.role,
            assigned_by_sub=principal.get("sub"),
        )
        return service.employee_payload(db, employee)
    except Exception as exc:
        _translate_service_error(exc)
