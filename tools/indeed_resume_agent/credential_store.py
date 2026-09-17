from __future__ import annotations

SERVICE_NAME = "ASIATI Resume Agent"
USERNAME = "agent-token"


class AgentCredentialMissing(RuntimeError):
    pass


def _load_keyring():
    import keyring
    return keyring


def read_agent_token() -> str:
    token = str(_load_keyring().get_password(SERVICE_NAME, USERNAME) or "").strip()
    if not token:
        raise AgentCredentialMissing(
            "No hay credencial del ASIATI Resume Agent en Windows Credential Manager."
        )
    return token


def write_agent_token(token: str) -> None:
    value = str(token or "").strip()
    if len(value) < 32:
        raise ValueError("Agent token must contain at least 32 characters")
    _load_keyring().set_password(SERVICE_NAME, USERNAME, value)


def delete_agent_token() -> None:
    _load_keyring().delete_password(SERVICE_NAME, USERNAME)
