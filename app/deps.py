"""FastAPI dependencies — DB session and HTTP authentication adapters."""

from typing import Generator

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

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
