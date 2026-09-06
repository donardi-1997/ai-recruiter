"""FastAPI dependencies — DB session, auth, etc."""

import hashlib
import logging
import os
from typing import Generator

import boto3
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import SessionLocal

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
# ADVISORY LOCK HELPERS
# ============================================================

def _advisory_lock_key(job_id: str) -> int:
    digest = hashlib.sha256(job_id.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, byteorder="big", signed=True)


def acquire_job_lock(db: Session, job_id: str) -> bool:
    from sqlalchemy import text

    lock_key = _advisory_lock_key(job_id)

    if "sqlite" in str(db.get_bind().url):
        return True

    result = db.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": lock_key},
    ).scalar()
    return bool(result)


def release_job_lock(db: Session, job_id: str) -> None:
    from sqlalchemy import text

    lock_key = _advisory_lock_key(job_id)

    if "sqlite" in str(db.get_bind().url):
        return

    db.execute(
        text("SELECT pg_advisory_unlock(:key)"),
        {"key": lock_key},
    )


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
            "sub": response.get("Username"),
            "email": attrs.get("email"),
        }
    except Exception as exc:
        logger.warning("Auth validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="Token invalido o expirado.")
