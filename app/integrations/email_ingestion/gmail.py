"""Configurable Gmail API transport for candidate email ingestion."""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from app.config import GmailSettings


@dataclass(frozen=True)
class GmailListResult:
    messages: list[dict[str, Any]]
    next_page_token: str | None


class GmailClient:
    """Small Gmail REST client using OAuth refresh tokens, never mailbox passwords."""

    def __init__(
        self,
        settings: GmailSettings,
        *,
        http_client: Any | None = None,
    ) -> None:
        self.settings = settings
        self._http = http_client or httpx.Client(
            timeout=settings.request_timeout_seconds
        )
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0

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
        response.raise_for_status()
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

        response = self._http.get(
            f"{self._user_base_url()}/messages",
            headers=self._headers(),
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
        return GmailListResult(
            messages=list(payload.get("messages") or []),
            next_page_token=payload.get("nextPageToken"),
        )

    def get_message(self, message_id: str) -> dict[str, Any]:
        """Return one complete Gmail message payload."""
        safe_message_id = quote(str(message_id), safe="")
        response = self._http.get(
            f"{self._user_base_url()}/messages/{safe_message_id}",
            headers=self._headers(),
            params={"format": "full"},
        )
        response.raise_for_status()
        return dict(response.json())

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        """Download and base64url-decode one Gmail attachment."""
        safe_message_id = quote(str(message_id), safe="")
        safe_attachment_id = quote(str(attachment_id), safe="")
        response = self._http.get(
            (
                f"{self._user_base_url()}/messages/{safe_message_id}"
                f"/attachments/{safe_attachment_id}"
            ),
            headers=self._headers(),
        )
        response.raise_for_status()
        encoded = str(response.json().get("data") or "")
        if not encoded:
            raise RuntimeError("GMAIL_ATTACHMENT_DATA_MISSING")
        padding = "=" * (-len(encoded) % 4)
        return base64.urlsafe_b64decode(encoded + padding)
