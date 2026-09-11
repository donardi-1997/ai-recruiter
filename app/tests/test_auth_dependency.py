import pytest
from fastapi import HTTPException, Request

import app.deps as deps


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


def test_valid_cognito_user_normalizes_sub_and_email(monkeypatch):
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

    monkeypatch.setattr(deps, "_get_cognito_client", lambda: FakeCognito())
    user = deps.get_current_user(_request("Bearer token-123"))
    assert user == {"sub": "stable-sub", "email": "person@example.com"}


def test_invalid_cognito_token_keeps_401_contract(monkeypatch):
    class FakeCognito:
        def get_user(self, *, AccessToken):
            raise RuntimeError("provider rejected token")

    monkeypatch.setattr(deps, "_get_cognito_client", lambda: FakeCognito())
    with pytest.raises(HTTPException) as exc_info:
        deps.get_current_user(_request("Bearer bad-token"))
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Token invalido o expirado."
