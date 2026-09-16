"""Authenticated routes for Gmail-backed candidate ingestion."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.domains.candidate_ingestion import gmail_integration

router = APIRouter(tags=["gmail-ingestion"])


def _translate(exc: Exception) -> HTTPException:
    if isinstance(
        exc,
        (gmail_integration.GmailDisabled, gmail_integration.GmailNotConfigured),
    ):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, gmail_integration.GmailRemoteError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail="Error interno del servidor.")


@router.get("/api/integrations/gmail/status")
def gmail_status(_user: dict = Depends(get_current_user)):
    return gmail_integration.integration_status()


@router.post("/api/integrations/gmail/sync")
def gmail_sync(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return gmail_integration.sync_mailbox(
            db,
            owner_sub=user["sub"],
        )
    except Exception as exc:
        raise _translate(exc)
