"""Authenticated routes for Gmail-backed candidate ingestion."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_gmail_oauth_settings
from app.deps import get_current_user, get_db
from app.domains.candidate_ingestion import gmail_integration, indeed_email_agent_service

router = APIRouter(tags=["gmail-ingestion"])


def _translate(exc: Exception) -> HTTPException:
    if isinstance(
        exc,
        (
            gmail_integration.GmailDisabled,
            gmail_integration.GmailNotConfigured,
            gmail_integration.GmailOAuthConfigurationError,
        ),
    ):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, gmail_integration.GmailOAuthOwnershipError):
        return HTTPException(
            status_code=403,
            detail="No tienes permisos para administrar la conexion corporativa de Gmail.",
        )
    if isinstance(exc, gmail_integration.GmailUnsafeConfiguration):
        return HTTPException(status_code=409, detail="La configuracion de Gmail no es segura.")
    if isinstance(exc, gmail_integration.GmailOAuthStateError):
        return HTTPException(status_code=400, detail="Invalid or expired Gmail OAuth state.")
    if isinstance(exc, gmail_integration.GmailRemoteError):
        if str(exc).startswith("GMAIL_TOKEN_REFRESH_REJECTED"):
            return HTTPException(
                status_code=502,
                detail="La conexion de Gmail expiro. Vuelve a conectarla.",
            )
        return HTTPException(
            status_code=502,
            detail="Gmail no pudo completar la operacion. Intenta nuevamente.",
        )
    return HTTPException(status_code=500, detail="Error interno del servidor.")


def _frontend_redirect(outcome: str) -> str:
    base = get_gmail_oauth_settings().frontend_return_url
    parts = urlsplit(base)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["gmail"] = outcome
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


@router.get("/api/integrations/gmail/status")
def gmail_status(user: dict = Depends(get_current_user)):
    return gmail_integration.integration_status(owner_sub=user["sub"])


@router.get("/api/integrations/gmail/oauth/start")
def gmail_oauth_start(user: dict = Depends(get_current_user)):
    try:
        return gmail_integration.oauth_start(owner_sub=user["sub"])
    except Exception as exc:
        raise _translate(exc)


@router.get("/api/integrations/gmail/oauth/callback")
def gmail_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    """Public Google redirect target protected by a signed, expiring OAuth state."""
    if error:
        return RedirectResponse(_frontend_redirect("denied"), status_code=302)
    if not code or not state:
        return RedirectResponse(_frontend_redirect("error"), status_code=302)
    try:
        gmail_integration.oauth_callback(code=code, state=state)
    except Exception:
        return RedirectResponse(_frontend_redirect("error"), status_code=302)
    return RedirectResponse(_frontend_redirect("connected"), status_code=302)


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


@router.post("/api/integrations/gmail/reset-to-current")
def gmail_reset_to_current(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return gmail_integration.reset_mailbox_to_current(
            db,
            owner_sub=user["sub"],
        )
    except Exception as exc:
        raise _translate(exc)




@router.get("/api/integrations/gmail/active-archived-test")
def gmail_active_archived_test(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return indeed_email_agent_service.get_active_smoke_task(
            db,
            owner_sub=user["sub"],
        )
    except Exception as exc:
        raise _translate(exc)


@router.post("/api/integrations/gmail/reactivate-one-archived")
def gmail_reactivate_one_archived(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return indeed_email_agent_service.reactivate_one_archived_task(
            db,
            owner_sub=user["sub"],
        )
    except Exception as exc:
        raise _translate(exc)


@router.post("/api/integrations/gmail/retry-active-archived-test")
def gmail_retry_active_archived_test(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return indeed_email_agent_service.retry_active_needs_human_task(
            db,
            owner_sub=user["sub"],
        )
    except Exception as exc:
        raise _translate(exc)


@router.delete("/api/integrations/gmail")
def gmail_disconnect(user: dict = Depends(get_current_user)):
    try:
        return gmail_integration.disconnect_oauth(owner_sub=user["sub"])
    except Exception as exc:
        raise _translate(exc)
