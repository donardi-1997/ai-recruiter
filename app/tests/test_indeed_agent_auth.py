"""Contracts for least-privilege machine authentication of the resume agent."""

from __future__ import annotations

import hashlib

import pytest
from fastapi import HTTPException

from app.config import IndeedResumeAgentSettings


class FakeStore:
    def __init__(self, payload):
        self.payload = dict(payload)

    def read(self):
        return dict(self.payload)


def _settings() -> IndeedResumeAgentSettings:
    return IndeedResumeAgentSettings(
        secret_id="/ai-recruiter/prod/indeed-resume-agent",
        lease_seconds=600,
        max_attempts=3,
        sender_domains=("indeedemail.com",),
        resume_host_suffixes=("indeed.com", "indeedemail.com"),
    )


def _payload(raw_token: str, *, enabled: bool = True, owner_sub: str = "owner-1"):
    return {
        "enabled": enabled,
        "owner_sub": owner_sub,
        "token_sha256": hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
    }


def test_missing_agent_token_returns_401_without_secret_material():
    from app.domains.candidate_ingestion.indeed_agent_auth import (
        authenticate_indeed_resume_agent,
    )

    token_hash = "a" * 64
    with pytest.raises(HTTPException) as caught:
        authenticate_indeed_resume_agent(
            None,
            settings=_settings(),
            secret_store=FakeStore(
                {
                    "enabled": True,
                    "owner_sub": "owner-1",
                    "token_sha256": token_hash,
                }
            ),
        )

    assert caught.value.status_code == 401
    assert token_hash not in str(caught.value.detail)


def test_disabled_agent_secret_returns_503():
    from app.domains.candidate_ingestion.indeed_agent_auth import (
        authenticate_indeed_resume_agent,
    )

    with pytest.raises(HTTPException) as caught:
        authenticate_indeed_resume_agent(
            "raw-token-value",
            settings=_settings(),
            secret_store=FakeStore(_payload("raw-token-value", enabled=False)),
        )

    assert caught.value.status_code == 503


def test_invalid_agent_token_returns_401_and_never_echoes_hash():
    from app.domains.candidate_ingestion.indeed_agent_auth import (
        authenticate_indeed_resume_agent,
    )

    payload = _payload("correct-token")
    with pytest.raises(HTTPException) as caught:
        authenticate_indeed_resume_agent(
            "wrong-token",
            settings=_settings(),
            secret_store=FakeStore(payload),
        )

    assert caught.value.status_code == 401
    assert payload["token_sha256"] not in str(caught.value.detail)
    assert "wrong-token" not in str(caught.value.detail)


def test_valid_agent_token_returns_owner_scoped_principal():
    from app.domains.candidate_ingestion.indeed_agent_auth import (
        authenticate_indeed_resume_agent,
    )

    principal = authenticate_indeed_resume_agent(
        "valid-agent-token",
        settings=_settings(),
        secret_store=FakeStore(
            _payload("valid-agent-token", owner_sub="cognito-owner-sub")
        ),
    )

    assert principal.owner_sub == "cognito-owner-sub"
    assert principal.__dict__ == {"owner_sub": "cognito-owner-sub"}


def test_malformed_secret_is_service_unavailable_without_leaking_payload():
    from app.domains.candidate_ingestion.indeed_agent_auth import (
        authenticate_indeed_resume_agent,
    )

    bad_hash = "not-a-valid-hash"
    with pytest.raises(HTTPException) as caught:
        authenticate_indeed_resume_agent(
            "valid-agent-token",
            settings=_settings(),
            secret_store=FakeStore(
                {
                    "enabled": True,
                    "owner_sub": "owner-1",
                    "token_sha256": bad_hash,
                }
            ),
        )

    assert caught.value.status_code == 503
    assert bad_hash not in str(caught.value.detail)
