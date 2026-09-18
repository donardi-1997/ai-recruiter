import pytest

from tools.indeed_resume_agent.credential_store import AgentCredentialMissing
from tools.indeed_resume_agent.main import resolve_agent_token


def test_existing_credential_does_not_prompt_or_write():
    token = "e" * 40
    prompted = []
    written = []

    result = resolve_agent_token(
        reader=lambda: token,
        writer=written.append,
        prompt=lambda: prompted.append(True) or "p" * 40,
    )

    assert result == token
    assert prompted == []
    assert written == []


def test_missing_credential_prompts_once_and_persists_locally():
    token = "p" * 40
    written = []

    def missing():
        raise AgentCredentialMissing("missing")

    result = resolve_agent_token(
        reader=missing,
        writer=written.append,
        prompt=lambda: token,
    )

    assert result == token
    assert written == [token]


@pytest.mark.parametrize("prompted", ["", None, "short"])
def test_missing_credential_rejects_cancelled_or_short_first_run_token(prompted):
    def missing():
        raise AgentCredentialMissing("missing")

    with pytest.raises(AgentCredentialMissing):
        resolve_agent_token(
            reader=missing,
            writer=lambda token: pytest.fail("invalid token must not be persisted"),
            prompt=lambda: prompted,
        )
