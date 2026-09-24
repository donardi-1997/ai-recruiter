"""FastAPI dependencies — DB session, authentication and authorization."""

from typing import Generator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.access_control import resolve_principal
from app.db import SessionLocal
from app.infrastructure.auth import cognito


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No token provided.")

    token = auth_header[7:]

    try:
        return cognito.validate_access_token(token)
    except cognito.CognitoAuthenticationError:
        raise HTTPException(status_code=401, detail="Token invalido o expirado.")


def get_current_principal(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Resolve the authenticated Cognito identity into the internal RBAC principal."""

    try:
        principal = resolve_principal(db, current_user)
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail="No fue posible asociar la cuenta con un perfil interno.",
        )

    if principal["profile"]["status"] != "ACTIVE":
        raise HTTPException(status_code=403, detail="La cuenta no esta activa.")
    return principal


def require_permission(permission_code: str):
    """FastAPI dependency requiring one granular permission."""

    def dependency(
        principal: dict = Depends(get_current_principal),
    ) -> dict:
        if permission_code not in set(principal.get("permissions") or []):
            raise HTTPException(
                status_code=403,
                detail="No tienes permisos para realizar esta accion.",
            )
        return principal

    return dependency


def require_role(role_code: str):
    """FastAPI dependency requiring one explicit role."""

    def dependency(
        principal: dict = Depends(get_current_principal),
    ) -> dict:
        if role_code not in set(principal.get("roles") or []):
            raise HTTPException(
                status_code=403,
                detail="No tienes el rol requerido para realizar esta accion.",
            )
        return principal

    return dependency
