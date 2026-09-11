import pytest
from fastapi import HTTPException, Request

import app.deps as deps
from app.infrastructure.auth import cognito


def _request(authorization: str | None = None) -> Request:
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("utf-8")))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def test_missing_authorization_header_keeps_401_contract():
    with pytest.raises(HTTPException) as exc_info:
        deps.get_current_user(_request())
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "No token provided."


def test_validate_access_token_normalizes_sub_and_email(monkeypatch):
    class FakeCognito:
        def get_user(self, *, AccessToken):
            assert AccessToken == "token-123"
            return {
                "Username": "legacy-user",
                "UserAttributes": [
                    {"Name": "sub", "Value": "stable-sub"},
                    {"Name": "email", "Value": "person@example.com"},
                ],
            }

    monkeypatch.setattr(cognito, "get_cognito_client", lambda: FakeCognito())
    user = cognito.validate_access_token("token-123")
    assert user == {"sub": "stable-sub", "email": "person@example.com"}


def test_validate_access_token_preserves_username_fallback(monkeypatch):
    class FakeCognito:
        def get_user(self, *, AccessToken):
            return {
                "Username": "legacy-user",
                "UserAttributes": [{"Name": "email", "Value": "person@example.com"}],
            }

    monkeypatch.setattr(cognito, "get_cognito_client", lambda: FakeCognito())
    user = cognito.validate_access_token("token-123")
    assert user == {"sub": "legacy-user", "email": "person@example.com"}


def test_validate_access_token_wraps_provider_failure(monkeypatch):
    class FakeCognito:
        def get_user(self, *, AccessToken):
            raise RuntimeError("provider rejected token")

    monkeypatch.setattr(cognito, "get_cognito_client", lambda: FakeCognito())
    with pytest.raises(cognito.CognitoAuthenticationError):
        cognito.validate_access_token("bad-token")


def test_invalid_cognito_token_keeps_401_contract(monkeypatch):
    def _reject(_token):
        raise cognito.CognitoAuthenticationError()

    monkeypatch.setattr(deps.cognito, "validate_access_token", _reject)
    with pytest.raises(HTTPException) as exc_info:
        deps.get_current_user(_request("Bearer bad-token"))
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Token invalido o expirado."
