"""Registration behavior for Cognito-backed accounts."""

from app import auth_routes


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


def test_register_auto_confirms_cognito_user(monkeypatch):
    signup_client = FakeSignupClient()
    admin_client = FakeAdminClient()

    monkeypatch.setattr(auth_routes, "cognito_client", signup_client)
    monkeypatch.setattr(
        auth_routes,
        "get_admin_cognito_client",
        lambda: admin_client,
        raising=False,
    )
    monkeypatch.setattr(
        auth_routes,
        "COGNITO_USER_POOL_ID",
        "us-east-2_TestPool",
        raising=False,
    )

    response = auth_routes.register(
        email="recruiter@example.com",
        password="StrongPass123",
    )

    assert signup_client.sign_up_call == {
        "ClientId": auth_routes.COGNITO_CLIENT_ID,
        "Username": "recruiter@example.com",
        "Password": "StrongPass123",
        "UserAttributes": [
            {"Name": "email", "Value": "recruiter@example.com"},
        ],
    }
    assert admin_client.confirm_call == {
        "UserPoolId": "us-east-2_TestPool",
        "Username": "recruiter@example.com",
    }
    assert response == {
        "message": "Usuario creado correctamente. Ya puedes iniciar sesion.",
        "user_sub": "user-sub-123",
    }
