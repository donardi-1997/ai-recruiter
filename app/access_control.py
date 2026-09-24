"""RBAC catalog and user-profile access resolution."""

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from app.models import Permission, Role, RolePermission, UserProfile, UserRole


SUPER_ADMIN = "SUPER_ADMIN"
ADMIN = "ADMIN"
EMPLOYEE = "EMPLOYEE"

ROLE_DEFINITIONS = {
    SUPER_ADMIN: (
        "Super administrador",
        "Acceso total, incluidas las funciones privadas de Dirección.",
    ),
    ADMIN: (
        "Administrador",
        "Administración de reclutamiento, empleados y capacitación.",
    ),
    EMPLOYEE: (
        "Empleado",
        "Acceso personal a capacitación, progreso y perfil.",
    ),
}

PERMISSION_DEFINITIONS = {
    "jobs.read": "Consultar vacantes.",
    "jobs.manage": "Crear y administrar vacantes.",
    "candidates.read": "Consultar candidatos y postulaciones.",
    "candidates.evaluate": "Evaluar y rankear candidatos.",
    "candidates.restrict": "Vetar o rehabilitar candidatos.",
    "ranking.read": "Consultar rankings de candidatos.",
    "integrations.manage": "Administrar integraciones del sistema.",
    "employees.read": "Consultar empleados.",
    "employees.create": "Crear empleados.",
    "employees.update": "Editar empleados.",
    "employees.disable": "Activar o desactivar empleados.",
    "employees.roles.manage": "Administrar roles de empleados.",
    "training.read": "Consultar el catálogo de capacitación.",
    "training.manage": "Crear y editar cursos, módulos y contenidos.",
    "training.assign": "Asignar capacitación a empleados.",
    "training.results.read": "Consultar resultados de capacitación.",
    "training.consume": "Consumir cursos y lecciones asignadas.",
    "training.quiz.take": "Presentar evaluaciones de capacitación.",
    "training.progress.read_own": "Consultar el progreso de capacitación propio.",
    "profile.read_own": "Consultar el perfil propio.",
    "employee_scores.read": "Consultar calificaciones privadas de empleados.",
    "employee_scores.create": "Agregar movimientos de puntuación.",
    "employee_scores.correct": "Corregir o anular movimientos de puntuación.",
    "employee_scores.export": "Exportar historial privado de puntuación.",
}

_ADMIN_PERMISSIONS = {
    "jobs.read",
    "jobs.manage",
    "candidates.read",
    "candidates.evaluate",
    "candidates.restrict",
    "ranking.read",
    "integrations.manage",
    "employees.read",
    "employees.create",
    "employees.update",
    "employees.disable",
    "employees.roles.manage",
    "training.read",
    "training.manage",
    "training.assign",
    "training.results.read",
    "training.consume",
    "training.quiz.take",
    "training.progress.read_own",
    "profile.read_own",
}

_EMPLOYEE_PERMISSIONS = {
    "training.read",
    "training.consume",
    "training.quiz.take",
    "training.progress.read_own",
    "profile.read_own",
}

ROLE_PERMISSION_MATRIX = {
    SUPER_ADMIN: set(PERMISSION_DEFINITIONS),
    ADMIN: _ADMIN_PERMISSIONS,
    EMPLOYEE: _EMPLOYEE_PERMISSIONS,
}


def normalize_email(email: str | None) -> str:
    return str(email or "").strip().casefold()


ROLE_RANK = {
    EMPLOYEE: 1,
    ADMIN: 2,
    SUPER_ADMIN: 3,
}


def _env_emails(name: str) -> set[str]:
    return {
        normalize_email(value)
        for value in os.getenv(name, "").split(",")
        if normalize_email(value)
    }


def bootstrap_role_for_email(email: str) -> str:
    """Return the minimum configured bootstrap role for one email."""

    normalized = normalize_email(email)
    if normalized in _env_emails("RBAC_BOOTSTRAP_SUPER_ADMIN_EMAILS"):
        return SUPER_ADMIN
    if normalized in _env_emails("RBAC_BOOTSTRAP_ADMIN_EMAILS"):
        return ADMIN
    return EMPLOYEE


def _ensure_minimum_role(
    db: Session,
    profile: UserProfile,
    role_code: str,
) -> None:
    current_roles = [
        code
        for (code,) in (
            db.query(UserRole.role_code)
            .filter(UserRole.user_id == profile.id)
            .all()
        )
    ]
    current_rank = max((ROLE_RANK.get(code, 0) for code in current_roles), default=0)
    target_rank = ROLE_RANK.get(role_code, 0)

    if current_rank >= target_rank:
        return

    db.query(UserRole).filter(UserRole.user_id == profile.id).delete(
        synchronize_session=False
    )
    assign_role(
        db,
        profile,
        role_code,
        assigned_by_sub="bootstrap-config",
    )


def ensure_rbac_catalog(db: Session) -> None:
    """Idempotently ensure the built-in roles, permissions and grants exist."""

    existing_roles = {row.code for row in db.query(Role).all()}
    for code, (name, description) in ROLE_DEFINITIONS.items():
        if code not in existing_roles:
            db.add(Role(code=code, name=name, description=description))

    existing_permissions = {row.code for row in db.query(Permission).all()}
    for code, description in PERMISSION_DEFINITIONS.items():
        if code not in existing_permissions:
            db.add(Permission(code=code, description=description))

    db.flush()

    existing_grants = {
        (row.role_code, row.permission_code)
        for row in db.query(RolePermission).all()
    }
    for role_code, permission_codes in ROLE_PERMISSION_MATRIX.items():
        for permission_code in permission_codes:
            pair = (role_code, permission_code)
            if pair not in existing_grants:
                db.add(
                    RolePermission(
                        role_code=role_code,
                        permission_code=permission_code,
                    )
                )

    db.flush()


def assign_role(
    db: Session,
    profile: UserProfile,
    role_code: str,
    *,
    assigned_by_sub: str | None = None,
) -> None:
    ensure_rbac_catalog(db)
    if role_code not in ROLE_DEFINITIONS:
        raise ValueError(f"Unknown role: {role_code}")

    existing = (
        db.query(UserRole)
        .filter(
            UserRole.user_id == profile.id,
            UserRole.role_code == role_code,
        )
        .one_or_none()
    )
    if existing is None:
        db.add(
            UserRole(
                user_id=profile.id,
                role_code=role_code,
                assigned_by_sub=assigned_by_sub,
            )
        )
        db.flush()


def ensure_user_profile(
    db: Session,
    identity: dict,
    *,
    default_role: str | None = None,
) -> UserProfile:
    """Get or create the internal profile for a validated Cognito identity."""

    sub = str(identity.get("sub") or "").strip()
    email = normalize_email(identity.get("email"))
    if not sub:
        raise ValueError("Authenticated identity does not contain a subject.")
    if not email:
        raise ValueError("Authenticated identity does not contain an email.")

    ensure_rbac_catalog(db)
    bootstrap_role = bootstrap_role_for_email(email)
    effective_default_role = default_role or bootstrap_role

    profile = (
        db.query(UserProfile)
        .filter(UserProfile.cognito_sub == sub)
        .one_or_none()
    )
    if profile is None:
        profile = UserProfile(
            cognito_sub=sub,
            email=email,
            onboarding_status="NOT_REQUIRED",
            status="ACTIVE",
        )
        db.add(profile)
        db.flush()
        assign_role(db, profile, effective_default_role)
    else:
        if normalize_email(profile.email) != email:
            profile.email = email
        has_role = (
            db.query(UserRole)
            .filter(UserRole.user_id == profile.id)
            .first()
            is not None
        )
        if not has_role:
            assign_role(db, profile, effective_default_role)

    _ensure_minimum_role(db, profile, bootstrap_role)

    db.commit()
    db.refresh(profile)
    return profile


def resolve_principal(db: Session, identity: dict) -> dict:
    """Return the authenticated user enriched with profile, roles and permissions."""

    profile = ensure_user_profile(db, identity)
    roles = sorted(
        role_code
        for (role_code,) in (
            db.query(UserRole.role_code)
            .filter(UserRole.user_id == profile.id)
            .all()
        )
    )
    permissions = sorted(
        permission_code
        for (permission_code,) in (
            db.query(RolePermission.permission_code)
            .filter(RolePermission.role_code.in_(roles))
            .distinct()
            .all()
        )
    )

    return {
        "sub": identity.get("sub"),
        "email": normalize_email(identity.get("email")),
        "email_verified": identity.get("email_verified"),
        "profile": {
            "id": profile.id,
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "job_title": profile.job_title,
            "department": profile.department,
            "hire_date": profile.hire_date.isoformat() if profile.hire_date else None,
            "onboarding_status": profile.onboarding_status,
            "onboarding_started_at": (
                profile.onboarding_started_at.isoformat()
                if profile.onboarding_started_at else None
            ),
            "onboarding_completed_at": (
                profile.onboarding_completed_at.isoformat()
                if profile.onboarding_completed_at else None
            ),
            "status": profile.status,
        },
        "roles": roles,
        "permissions": permissions,
    }
