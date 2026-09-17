"""Machine authentication for the Indeed resume download agent."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass

from fastapi import Header, HTTPException

from app.config import IndeedResumeAgentSettings, get_indeed_resume_agent_settings
from app.infrastructure.indeed_resume_agent_secret import IndeedResumeAgentSecretStore

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class AgentPrincipal:
    owner_sub: str


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Invalid agent credential")


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="Indeed resume agent is unavailable")


def authenticate_indeed_resume_agent(
    token: str | None,
    *,
    settings: IndeedResumeAgentSettings | None = None,
    secret_store=None,
) -> AgentPrincipal:
    """Validate the machine token without returning or logging secret material."""
    if not token:
        raise _unauthorized()

    resolved_settings = settings or get_indeed_resume_agent_settings()
    store = secret_store or IndeedResumeAgentSecretStore(resolved_settings.secret_id)
    try:
        payload = store.read()
    except Exception as exc:
        raise _unavailable() from exc

    if payload.get("enabled") is not True:
        raise _unavailable()

    owner_sub = str(payload.get("owner_sub") or "").strip()
    expected_digest = str(payload.get("token_sha256") or "").strip()
    if not owner_sub or not _SHA256_HEX_RE.fullmatch(expected_digest):
        raise _unavailable()

    supplied_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(supplied_digest, expected_digest):
        raise _unauthorized()

    return AgentPrincipal(owner_sub=owner_sub)


def get_indeed_resume_agent_principal(
    token: str | None = Header(default=None, alias="X-ASIATI-Agent-Token"),
) -> AgentPrincipal:
    """FastAPI dependency for owner-scoped machine authentication."""
    return authenticate_indeed_resume_agent(token)
