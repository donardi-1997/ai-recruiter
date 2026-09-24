import json

"""Registration behavior for Cognito-backed accounts."""

from app import auth_routes
from botocore.exceptions import ClientError


class FakeSignupClient:
    def __init__(self):
        self.sign_up_call = None

    def sign_up(self, **kwargs):
        self.sign_up_call = kwargs
        return {"UserSub": "user-sub-123"}


class FakeAdminClient:
    def __init__(self):
        self.confirm_call = None

    def admin_confirm_sign_up(self, **kwargs):
        self.confirm_call = kwargs
        return {}


class FakeSession:
    def __init__(self, admin_client):
        self.admin_client = admin_client
        self.client_call = None

    def client(self, service_name, region_name=None):
        self.client_call = {
            "service_name": service_name,
            "region_name": region_name,
        }
        return self.admin_client


def test_register_auto_confirms_cognito_user_with_signed_session(monkeypatch):
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "true")
    signup_client = FakeSignupClient()
    admin_client = FakeAdminClient()
    session = FakeSession(admin_client)

    monkeypatch.setattr(auth_routes, "cognito_client", signup_client)
    monkeypatch.setattr(
        auth_routes,
        "get_cached_session",
        lambda: session,
        raising=False,
    )
    monkeypatch.setattr(
        auth_routes,
        "COGNITO_USER_POOL_ID",
        "us-east-2_TestPool",
        raising=False,
    )

    response = auth_routes.register(
        auth_routes.RegisterRequest(
            email="recruiter@example.com",
            password="StrongPass123",
        )
    )

    assert signup_client.sign_up_call == {
        "ClientId": auth_routes.COGNITO_CLIENT_ID,
        "Username": "recruiter@example.com",
        "Password": "StrongPass123",
        "UserAttributes": [
            {"Name": "email", "Value": "recruiter@example.com"},
        ],
    }
    assert session.client_call == {
        "service_name": "cognito-idp",
        "region_name": "us-east-2",
    }
    assert admin_client.confirm_call == {
        "UserPoolId": "us-east-2_TestPool",
        "Username": "recruiter@example.com",
    }
    assert response == {
        "message": "Usuario creado correctamente. Ya puedes iniciar sesion.",
        "user_sub": "user-sub-123",
    }


def test_register_contract_keeps_password_out_of_query_parameters():
    import inspect

    signature = inspect.signature(auth_routes.register)
    assert list(signature.parameters) == ["body"]
    assert signature.parameters["body"].annotation is auth_routes.RegisterRequest

    source = inspect.getsource(auth_routes.register)
    assert "Query(" not in source


def test_public_registration_is_disabled_by_default(monkeypatch):
    import pytest
    from fastapi import HTTPException

    monkeypatch.delenv("ALLOW_PUBLIC_REGISTRATION", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        auth_routes.register(
            auth_routes.RegisterRequest(
                email="employee@example.com",
                password="StrongPass123",
            )
        )

    assert exc_info.value.status_code == 403
    assert "registro publico" in exc_info.value.detail.casefold()


def test_register_normalizes_email_before_provider_call(monkeypatch):
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "true")
    signup_client = FakeSignupClient()
    admin_client = FakeAdminClient()
    session = FakeSession(admin_client)

    monkeypatch.setattr(auth_routes, "cognito_client", signup_client)
    monkeypatch.setattr(auth_routes, "get_cached_session", lambda: session)
    monkeypatch.setattr(auth_routes, "COGNITO_USER_POOL_ID", "us-east-2_TestPool")

    auth_routes.register(
        auth_routes.RegisterRequest(
            email="  Recruiter@Example.COM ",
            password="StrongPass123",
        )
    )

    assert signup_client.sign_up_call["Username"] == "recruiter@example.com"


def test_register_does_not_expose_provider_error_message(monkeypatch):
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "true")

    class RejectingSignupClient:
        def sign_up(self, **kwargs):
            raise ClientError(
                {
                    "Error": {
                        "Code": "InternalErrorException",
                        "Message": "secret provider detail token=abc123",
                    }
                },
                "SignUp",
            )

    monkeypatch.setattr(auth_routes, "cognito_client", RejectingSignupClient())
    monkeypatch.setattr(auth_routes, "COGNITO_USER_POOL_ID", "us-east-2_TestPool")

    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        auth_routes.register(
            auth_routes.RegisterRequest(
                email="recruiter@example.com",
                password="StrongPass123",
            )
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "No fue posible crear la cuenta."
    assert "secret provider detail" not in exc_info.value.detail


class FakeLoginClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def initiate_auth(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.response)


def test_login_returns_only_access_token_and_sets_lax_refresh_cookie(monkeypatch):
    client = FakeLoginClient(
        {
            "AuthenticationResult": {
                "AccessToken": "access-token",
                "IdToken": "id-token-should-not-be-returned",
                "RefreshToken": "refresh-token",
                "ExpiresIn": 3600,
            }
        }
    )
    monkeypatch.setattr(auth_routes, "cognito_client", client)

    response = auth_routes.login(
        auth_routes.LoginRequest(
            email="Recruiter@Example.COM",
            password="pw",
        )
    )

    payload = json.loads(response.body.decode("utf-8"))
    assert payload == {
        "access_token": "access-token",
        "expires_in": 3600,
    }
    set_cookie = response.headers["set-cookie"].casefold()
    assert "httponly" in set_cookie
    assert "secure" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "id-token-should-not-be-returned" not in response.body.decode("utf-8")


def test_login_rejects_challenge_without_access_token(monkeypatch):
    client = FakeLoginClient({"ChallengeName": "SMS_MFA"})
    monkeypatch.setattr(auth_routes, "cognito_client", client)

    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        auth_routes.login(
            auth_routes.LoginRequest(
                email="recruiter@example.com",
                password="pw",
            )
        )

    assert exc_info.value.status_code == 403
    assert "paso adicional" in exc_info.value.detail
