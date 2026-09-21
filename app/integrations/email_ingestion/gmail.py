"""Configurable Gmail API transport for candidate email ingestion."""

from __future__ import annotations

import base64
import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from app.config import GmailSettings


class GmailHistoryExpired(RuntimeError):
    """Raised when Gmail can no longer serve an incremental history cursor."""


class GmailTokenRefreshRejected(RuntimeError):
    """Google rejected the configured OAuth refresh token/client pair."""


class GmailApiUnauthorized(RuntimeError):
    """Gmail API rejected the access token."""


class GmailApiPermissionDenied(RuntimeError):
    """Gmail API denied the requested operation."""


class GmailApiHttpError(RuntimeError):
    """Gmail API returned an unexpected non-success HTTP status."""


_SAFE_GOOGLE_REASONS = {
    "insufficientPermissions",
    "accessNotConfigured",
    "forbidden",
    "userRateLimitExceeded",
    "rateLimitExceeded",
    "dailyLimitExceeded",
    "domainPolicy",
    "authError",
}


def _safe_google_reason(response) -> str:
    """Return a machine-safe Google reason code without exposing response messages."""
    try:
        payload = response.json()
    except Exception:
        return "UNKNOWN"
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        errors = error.get("errors")
        if isinstance(errors, list):
            for item in errors:
                if isinstance(item, dict):
                    reason = str(item.get("reason") or "").strip()
                    if reason in _SAFE_GOOGLE_REASONS:
                        return reason
        status = str(error.get("status") or "").strip()
        if status in {"PERMISSION_DENIED", "UNAUTHENTICATED", "RESOURCE_EXHAUSTED"}:
            return status
    return "UNKNOWN"


def _ensure_google_success(response, *, operation: str) -> None:
    """Classify Google HTTP failures without exposing response bodies or tokens."""
    status = int(getattr(response, "status_code", 0) or 0)
    if 200 <= status < 300:
        return
    if operation == "token_refresh":
        raise GmailTokenRefreshRejected("GMAIL_TOKEN_REFRESH_REJECTED")
    reason = _safe_google_reason(response)
    if status == 401:
        raise GmailApiUnauthorized(f"GMAIL_API_UNAUTHORIZED:{operation}:{reason}")
    if status == 403:
        raise GmailApiPermissionDenied(
            f"GMAIL_API_PERMISSION_DENIED:{operation}:{reason}"
        )
    raise GmailApiHttpError(
        f"GMAIL_API_HTTP_{status or 'UNKNOWN'}:{operation}:{reason}"
    )


@dataclass(frozen=True)
class GmailListResult:
    messages: list[dict[str, Any]]
    next_page_token: str | None


@dataclass(frozen=True)
class GmailProfile:
    email_address: str
    history_id: str


@dataclass(frozen=True)
class GmailHistoryResult:
    message_ids: tuple[str, ...]
    history_id: str
    next_page_token: str | None


class GmailClient:
    """Small Gmail REST client using OAuth refresh tokens, never mailbox passwords."""

    _RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}
    _MAX_RATE_LIMIT_RETRIES = 3
    _MAX_BACKOFF_SECONDS = 8.0

    def __init__(
        self,
        settings: GmailSettings,
        *,
        http_client: Any | None = None,
        sleep_fn=time.sleep,
        jitter_fn=random.random,
    ) -> None:
        self.settings = settings
        self._http = http_client or httpx.Client(
            timeout=settings.request_timeout_seconds
        )
        self._sleep = sleep_fn
        self._jitter = jitter_fn
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0

    @classmethod
    def _is_rate_limited(cls, response) -> bool:
        status = int(getattr(response, "status_code", 0) or 0)
        if status == 429:
            return True
        if status != 403:
            return False
        return _safe_google_reason(response) in cls._RATE_LIMIT_REASONS

    @staticmethod
    def _retry_after_seconds(response) -> float | None:
        headers = getattr(response, "headers", None) or {}
        raw = str(headers.get("Retry-After") or "").strip()
        if not raw:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if value < 0:
            return None
        return value

    def _gmail_get(self, url: str, **kwargs):
        """GET Gmail resources with bounded exponential backoff for rate limits."""
        for attempt in range(self._MAX_RATE_LIMIT_RETRIES + 1):
            response = self._http.get(url, **kwargs)
            if not self._is_rate_limited(response):
                return response
            if attempt >= self._MAX_RATE_LIMIT_RETRIES:
                return response

            retry_after = self._retry_after_seconds(response)
            if retry_after is not None:
                delay = min(retry_after, self._MAX_BACKOFF_SECONDS)
            else:
                delay = min(
                    (2**attempt) + float(self._jitter()),
                    self._MAX_BACKOFF_SECONDS,
                )
            self._sleep(max(0.0, delay))

        raise RuntimeError("GMAIL_RATE_LIMIT_RETRY_LOOP_INVALID")

    def refresh_access_token(self) -> str:
        """Exchange the configured refresh token for a short-lived access token."""
        if not self.settings.configured:
            raise RuntimeError("GMAIL_NOT_CONFIGURED")

        response = self._http.post(
            self.settings.token_url,
            data={
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
                "refresh_token": self.settings.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        _ensure_google_success(response, operation="token_refresh")
        payload = response.json()
        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise RuntimeError("GMAIL_OAUTH_TOKEN_MISSING")

        expires_in = max(60, int(payload.get("expires_in") or 3600))
        self._access_token = token
        self._access_token_expires_at = time.monotonic() + max(1, expires_in - 60)
        return token

    def get_access_token(self) -> str:
        if (
            self._access_token
            and time.monotonic() < self._access_token_expires_at
        ):
            return self._access_token
        return self.refresh_access_token()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_access_token()}"}

    def _user_base_url(self) -> str:
        user_id = quote(self.settings.user_id, safe="@._-+")
        return f"{self.settings.api_base_url}/users/{user_id}"

    def get_profile(self) -> GmailProfile:
        """Discover the identity and current history cursor of the authorized mailbox."""
        response = self._gmail_get(
            f"{self._user_base_url()}/profile",
            headers=self._headers(),
        )
        _ensure_google_success(response, operation="get_profile")
        payload = response.json()
        email_address = str(payload.get("emailAddress") or "").strip().casefold()
        history_id = str(payload.get("historyId") or "").strip()
        if not email_address or not history_id:
            raise RuntimeError("GMAIL_PROFILE_INCOMPLETE")
        return GmailProfile(email_address=email_address, history_id=history_id)

    def list_messages(
        self,
        *,
        page_token: str | None = None,
        max_results: int = 100,
    ) -> GmailListResult:
        """List message identifiers matching the configured Gmail query."""
        bounded_max_results = max(1, min(int(max_results), 500))
        params: dict[str, Any] = {
            "q": self.settings.query,
            "maxResults": bounded_max_results,
        }
        if page_token:
            params["pageToken"] = page_token

        response = self._gmail_get(
            f"{self._user_base_url()}/messages",
            headers=self._headers(),
            params=params,
        )
        _ensure_google_success(response, operation="list_messages")
        payload = response.json()
        return GmailListResult(
            messages=list(payload.get("messages") or []),
            next_page_token=payload.get("nextPageToken"),
        )

    def list_history(
        self,
        *,
        start_history_id: str,
        page_token: str | None = None,
        max_results: int = 100,
    ) -> GmailHistoryResult:
        """List unique INBOX message additions since a durable Gmail history cursor."""
        bounded_max_results = max(1, min(int(max_results), 500))
        params: dict[str, Any] = {
            "startHistoryId": str(start_history_id),
            "historyTypes": "messageAdded",
            "labelId": "INBOX",
            "maxResults": bounded_max_results,
        }
        if page_token:
            params["pageToken"] = page_token

        response = self._gmail_get(
            f"{self._user_base_url()}/history",
            headers=self._headers(),
            params=params,
        )
        if response.status_code == 404:
            raise GmailHistoryExpired("GMAIL_HISTORY_EXPIRED")
        _ensure_google_success(response, operation="list_history")
        payload = response.json()

        ordered_ids: list[str] = []
        seen: set[str] = set()
        for entry in payload.get("history") or []:
            for added in entry.get("messagesAdded") or []:
                message_id = str((added.get("message") or {}).get("id") or "").strip()
                if message_id and message_id not in seen:
                    seen.add(message_id)
                    ordered_ids.append(message_id)

        history_id = str(payload.get("historyId") or start_history_id).strip()
        return GmailHistoryResult(
            message_ids=tuple(ordered_ids),
            history_id=history_id,
            next_page_token=payload.get("nextPageToken"),
        )

    def get_message(self, message_id: str) -> dict[str, Any]:
        """Return one complete Gmail message payload."""
        safe_message_id = quote(str(message_id), safe="")
        response = self._gmail_get(
            f"{self._user_base_url()}/messages/{safe_message_id}",
            headers=self._headers(),
            params={"format": "full"},
        )
        _ensure_google_success(response, operation="get_message")
        return dict(response.json())

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        """Download and base64url-decode one Gmail attachment."""
        safe_message_id = quote(str(message_id), safe="")
        safe_attachment_id = quote(str(attachment_id), safe="")
        response = self._gmail_get(
            (
                f"{self._user_base_url()}/messages/{safe_message_id}"
                f"/attachments/{safe_attachment_id}"
            ),
            headers=self._headers(),
        )
        _ensure_google_success(response, operation="get_attachment")
        encoded = str(response.json().get("data") or "")
        if not encoded:
            raise RuntimeError("GMAIL_ATTACHMENT_DATA_MISSING")
        padding = "=" * (-len(encoded) % 4)
        return base64.urlsafe_b64decode(encoded + padding)
