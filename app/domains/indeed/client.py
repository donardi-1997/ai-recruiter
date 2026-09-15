"""Indeed OAuth and GraphQL transport."""

import time

import httpx

from app.config import IndeedSettings
from app.domains.indeed.exceptions import IndeedRemoteError


class IndeedClient:
    def __init__(
        self,
        settings: IndeedSettings,
        http: httpx.Client | None = None,
        *,
        include_employer: bool = True,
    ):
        self.settings = settings
        self.http = http or httpx.Client(timeout=settings.request_timeout_seconds)
        self.include_employer = include_employer
        self._token: str | None = None
        self._token_expires_at = 0.0

    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        data = {
            "client_id": self.settings.client_id,
            "client_secret": self.settings.client_secret,
            "grant_type": "client_credentials",
            "scope": self.settings.scope,
        }
        if self.include_employer and self.settings.employer_id:
            data["employer"] = self.settings.employer_id
        try:
            response = self.http.post(
                self.settings.token_url,
                data=data,
                headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            payload = response.json()
            token = payload.get("access_token")
            if not token:
                raise IndeedRemoteError("Indeed OAuth response did not include access_token")
            expires_in = int(payload.get("expires_in", 3600))
            self._token = token
            self._token_expires_at = time.monotonic() + max(1, expires_in - 60)
            return token
        except IndeedRemoteError:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise IndeedRemoteError(f"Indeed OAuth failed: {exc}") from exc

    def execute(self, query: str, variables: dict | None = None) -> dict:
        token = self._access_token()
        try:
            response = self.http.post(
                self.settings.graphql_url,
                json={"query": query, "variables": variables or {}},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise IndeedRemoteError(f"Indeed GraphQL request failed: {exc}") from exc
        if payload.get("errors"):
            messages = "; ".join(str(error.get("message", error)) for error in payload["errors"])
            raise IndeedRemoteError(f"Indeed GraphQL error: {messages}")
        if "data" not in payload:
            raise IndeedRemoteError("Indeed GraphQL response did not include data")
        return payload["data"]
