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
