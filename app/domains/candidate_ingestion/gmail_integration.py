"""Composition layer for the configurable Gmail candidate-ingestion adapter."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.config import (
    GmailOAuthSettings,
    GmailSettings,
    get_gmail_oauth_settings,
    get_gmail_settings,
)
from app.domains.candidate_ingestion.mailbox_sync import sync_gmail_mailbox
from app.infrastructure.gmail_oauth_store import GmailOAuthSecretStore
from app.integrations.email_ingestion.gmail import (
    GmailApiHttpError,
    GmailApiPermissionDenied,
    GmailApiUnauthorized,
    GmailClient,
    GmailTokenRefreshRejected,
)


class GmailDisabled(RuntimeError):
    pass


class GmailNotConfigured(RuntimeError):
    pass


class GmailUnsafeConfiguration(RuntimeError):
    pass


class GmailRemoteError(RuntimeError):
    pass


class GmailOAuthStateError(RuntimeError):
    pass


class GmailOAuthConfigurationError(RuntimeError):
    pass


def is_safe_mailbox_filter(settings: GmailSettings) -> bool:
    """Require either a sender allowlist or an explicit Gmail from: restriction."""
    if settings.allowed_senders:
        return True
    query = str(settings.query or "").casefold()
    return "from:" in query


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _oauth_store(
    oauth_settings: GmailOAuthSettings,
    oauth_store: Any | None,
):
    return oauth_store or GmailOAuthSecretStore(oauth_settings.secret_id)


def _read_oauth_secret(
    oauth_settings: GmailOAuthSettings,
    oauth_store: Any | None,
    *,
    tolerate_unavailable: bool = False,
) -> dict:
    store = _oauth_store(oauth_settings, oauth_store)
    try:
        payload = store.read()
    except Exception:
        if tolerate_unavailable:
            return {}
        raise
    return dict(payload or {})


def _secret_bool(secret_payload: dict, key: str, fallback: bool) -> bool:
    """Resolve an optional JSON boolean while retaining env fallback semantics."""
    if key not in secret_payload:
        return fallback
    value = secret_payload.get(key)
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _secret_allowed_senders(
    secret_payload: dict,
    fallback: tuple[str, ...],
) -> tuple[str, ...]:
    """Normalize an optional JSON list or comma-separated sender allowlist."""
    if "allowed_senders" not in secret_payload:
        return fallback
    raw = secret_payload.get("allowed_senders")
    values = raw.split(",") if isinstance(raw, str) else raw
    if not isinstance(values, (list, tuple, set)):
        return ()
    return tuple(
        str(value).strip().casefold()
        for value in values
        if str(value).strip()
    )


def _resolved_gmail_settings(
    settings: GmailSettings,
    secret_payload: dict,
) -> GmailSettings:
    """Overlay runtime Gmail values while preserving environment fallback for local dev."""
    query = (
        str(secret_payload.get("query") or "").strip()
        if "query" in secret_payload
        else settings.query
    )
    provider = (
        str(secret_payload.get("ingestion_provider") or "").strip().upper()
        if "ingestion_provider" in secret_payload
        else settings.ingestion_provider
    )
    return replace(
        settings,
        enabled=_secret_bool(secret_payload, "enabled", settings.enabled),
        client_id=str(secret_payload.get("client_id") or settings.client_id or "").strip(),
        client_secret=str(
            secret_payload.get("client_secret") or settings.client_secret or ""
        ).strip(),
        refresh_token=str(
            secret_payload.get("refresh_token") or settings.refresh_token or ""
        ).strip(),
        query=query,
        allowed_senders=_secret_allowed_senders(
            secret_payload,
            settings.allowed_senders,
        ),
        ingestion_provider=provider or settings.ingestion_provider,
    )


def _resolved_oauth_settings(
    settings: GmailOAuthSettings,
    secret_payload: dict,
) -> GmailOAuthSettings:
    """Allow the production callback URI to live in Secrets Manager."""
    return replace(
        settings,
        redirect_uri=str(
            secret_payload.get("redirect_uri") or settings.redirect_uri or ""
        ).strip(),
    )


def _oauth_is_configured(oauth_settings: GmailOAuthSettings, payload: dict) -> bool:
    return bool(
        oauth_settings.redirect_uri
        and str(payload.get("client_id") or "").strip()
        and str(payload.get("client_secret") or "").strip()
        and str(payload.get("state_secret") or "").strip()
    )


def integration_status(
    *,
    settings: GmailSettings | None = None,
    oauth_settings: GmailOAuthSettings | None = None,
    oauth_store=None,
) -> dict:
    current = settings or get_gmail_settings()
    oauth = oauth_settings or get_gmail_oauth_settings()
    payload = _read_oauth_secret(
        oauth,
        oauth_store,
        tolerate_unavailable=True,
    )
    resolved = _resolved_gmail_settings(current, payload)
    resolved_oauth = _resolved_oauth_settings(oauth, payload)
    connected_email = str(payload.get("connected_email") or "").strip().casefold()
    connected = bool(resolved.refresh_token and connected_email)
    return {
        "enabled": resolved.enabled,
        "configured": resolved.configured,
        "oauth_configured": _oauth_is_configured(resolved_oauth, payload),
        "connected": connected,
        "connected_email": connected_email or None,
        "provider": resolved.ingestion_provider,
        "safe_filter": is_safe_mailbox_filter(resolved),
        "redirect_uri": resolved_oauth.redirect_uri or None,
    }


def _sign_state(payload: dict, state_secret: str) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = _b64encode(body)
    signature = hmac.new(
        state_secret.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded}.{_b64encode(signature)}"


def _verify_state(
    state: str,
    state_secret: str,
    max_age_seconds: int,
) -> dict:
    try:
        encoded, supplied_signature = str(state or "").split(".", 1)
        expected_signature = hmac.new(
            state_secret.encode("utf-8"),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).digest()
        supplied = _b64decode(supplied_signature)
        if not hmac.compare_digest(supplied, expected_signature):
            raise GmailOAuthStateError("GMAIL_OAUTH_STATE_INVALID")
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
        issued_at = int(payload["iat"])
    except GmailOAuthStateError:
        raise
    except Exception as exc:
        raise GmailOAuthStateError("GMAIL_OAUTH_STATE_INVALID") from exc

    now = int(time.time())
    if issued_at > now + 30 or now - issued_at > max_age_seconds:
        raise GmailOAuthStateError("GMAIL_OAUTH_STATE_EXPIRED")
    if not str(payload.get("sub") or "").strip():
        raise GmailOAuthStateError("GMAIL_OAUTH_STATE_INVALID")
    return payload


def oauth_start(
    *,
    owner_sub: str,
    settings: GmailSettings | None = None,
    oauth_settings: GmailOAuthSettings | None = None,
    oauth_store=None,
) -> dict:
    """Build Google's authorization URL without exposing client secrets."""
    current = settings or get_gmail_settings()
    oauth = oauth_settings or get_gmail_oauth_settings()
    payload = _read_oauth_secret(oauth, oauth_store)
    resolved_oauth = _resolved_oauth_settings(oauth, payload)
    if not _oauth_is_configured(resolved_oauth, payload):
        raise GmailOAuthConfigurationError("Gmail OAuth client is not configured.")

    state_secret = str(payload["state_secret"])
    state = _sign_state(
        {
            "sub": owner_sub,
            "iat": int(time.time()),
            "nonce": secrets.token_urlsafe(16),
        },
        state_secret,
    )
    query = urlencode(
        {
            "client_id": str(payload["client_id"]),
            "redirect_uri": resolved_oauth.redirect_uri,
            "response_type": "code",
            "scope": current.scope,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
    )
    return {"authorization_url": f"{resolved_oauth.authorization_url}?{query}"}


def oauth_callback(
    *,
    code: str,
    state: str,
    settings: GmailSettings | None = None,
    oauth_settings: GmailOAuthSettings | None = None,
    oauth_store=None,
    http_client: Any | None = None,
) -> dict:
    """Validate the callback, persist the refresh token, and identify the mailbox."""
    current = settings or get_gmail_settings()
    oauth = oauth_settings or get_gmail_oauth_settings()
    store = _oauth_store(oauth, oauth_store)
    payload = dict(store.read() or {})
    resolved_oauth = _resolved_oauth_settings(oauth, payload)
    if not _oauth_is_configured(resolved_oauth, payload):
        raise GmailOAuthConfigurationError("Gmail OAuth client is not configured.")

    _verify_state(
        state,
        str(payload["state_secret"]),
        resolved_oauth.state_max_age_seconds,
    )

    client = http_client or httpx.Client(timeout=current.request_timeout_seconds)
    try:
        token_response = client.post(
            resolved_oauth.token_url,
            data={
                "code": code,
                "client_id": str(payload["client_id"]),
                "client_secret": str(payload["client_secret"]),
                "redirect_uri": resolved_oauth.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        access_token = str(token_payload.get("access_token") or "").strip()
        refresh_token = str(
            token_payload.get("refresh_token") or payload.get("refresh_token") or ""
        ).strip()
        if not access_token or not refresh_token:
            raise GmailRemoteError("Google OAuth did not return the required tokens.")

        profile_response = client.get(
            f"{current.api_base_url}/users/me/profile",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        profile_response.raise_for_status()
        connected_email = str(
            profile_response.json().get("emailAddress") or ""
        ).strip().casefold()
        if not connected_email:
            raise GmailRemoteError("Gmail profile did not include an email address.")
    except GmailRemoteError:
        raise
    except Exception as exc:
        raise GmailRemoteError("Google OAuth callback failed.") from exc

    updated = dict(payload)
    updated.update(
        {
            "refresh_token": refresh_token,
            "connected_email": connected_email,
            "connected_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    store.write(updated)
    return {
        "connected": True,
        "connected_email": connected_email,
    }


def disconnect_oauth(*, oauth_store=None) -> dict:
    """Forget the mailbox grant while preserving the OAuth client configuration."""
    oauth = get_gmail_oauth_settings()
    store = _oauth_store(oauth, oauth_store)
    payload = dict(store.read() or {})
    payload["refresh_token"] = ""
    payload["connected_email"] = ""
    payload.pop("connected_at", None)
    store.write(payload)
    return {"connected": False}


def sync_mailbox(
    db: Session,
    *,
    owner_sub: str,
    settings: GmailSettings | None = None,
    oauth_settings: GmailOAuthSettings | None = None,
    oauth_store=None,
    mailbox_client=None,
    storage=None,
) -> dict:
    """Run one authenticated Gmail sync without exposing OAuth credentials."""
    current = settings or get_gmail_settings()
    oauth = oauth_settings or get_gmail_oauth_settings()
    payload = _read_oauth_secret(
        oauth,
        oauth_store,
        tolerate_unavailable=True,
    )
    resolved = _resolved_gmail_settings(current, payload)
    if not resolved.enabled:
        raise GmailDisabled("Gmail ingestion is disabled.")
    if not resolved.configured:
        raise GmailNotConfigured("Gmail OAuth is not configured.")
    if not is_safe_mailbox_filter(resolved):
        raise GmailUnsafeConfiguration(
            "Gmail ingestion requires GMAIL_ALLOWED_SENDERS or a restrictive from: query."
        )

    client = mailbox_client or GmailClient(resolved)
    try:
        result = sync_gmail_mailbox(
            db,
            owner_sub=owner_sub,
            provider=resolved.ingestion_provider,
            mailbox_client=client,
            allowed_senders=resolved.allowed_senders,
            storage=storage,
        )
        return asdict(result)
    except GmailTokenRefreshRejected as exc:
        raise GmailRemoteError(
            "GMAIL_TOKEN_REFRESH_REJECTED: vuelve a conectar la cuenta de Gmail."
        ) from exc
    except GmailApiUnauthorized as exc:
        raise GmailRemoteError(
            "GMAIL_API_UNAUTHORIZED: vuelve a conectar la cuenta de Gmail."
        ) from exc
    except GmailApiPermissionDenied as exc:
        raise GmailRemoteError(
            "GMAIL_API_PERMISSION_DENIED: verifica el permiso gmail.readonly y vuelve a conectar Gmail."
        ) from exc
    except GmailApiHttpError as exc:
        raise GmailRemoteError(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise GmailRemoteError("GMAIL_NETWORK_ERROR: no fue posible contactar Google.") from exc
    except RuntimeError as exc:
        code = str(exc)
        if code == "GMAIL_NOT_CONFIGURED":
            raise GmailNotConfigured("Gmail OAuth is not configured.") from exc
        if code.startswith("GMAIL_"):
            raise GmailRemoteError("Gmail API request failed.") from exc
        raise
