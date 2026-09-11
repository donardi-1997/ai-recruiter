"""FastAPI dependencies — DB session, auth, etc."""

import logging
import os
from typing import Generator

import boto3
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.infrastructure.locking.job_lock import (
    acquire_job_lock,
    advisory_lock_key as _advisory_lock_key,
    release_job_lock,
)

logger = logging.getLogger(__name__)


# ============================================================
# DATABASE SESSION
# ============================================================

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================
# AUTH — Cognito JWT validation
# ============================================================

_cognito_client = None


def _get_cognito_client():
    global _cognito_client
    if _cognito_client is None:
        _cognito_client = boto3.client(
            "cognito-idp",
            region_name=os.getenv("AWS_REGION", "us-east-2"),
        )
    return _cognito_client


def get_current_user(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No token provided.")

    token = auth_header[7:]

    try:
        cognito = _get_cognito_client()
        response = cognito.get_user(AccessToken=token)
        attrs = {a["Name"]: a["Value"] for a in response.get("UserAttributes", [])}
        return {
            # "sub" is the stable Cognito user identifier.
            # Username is only a compatibility fallback.
            "sub": attrs.get("sub") or response.get("Username"),
            "email": attrs.get("email"),
        }
    except Exception as exc:
        logger.warning("Auth validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="Token invalido o expirado.")
