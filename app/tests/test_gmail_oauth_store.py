from app.infrastructure import gmail_oauth_store


def test_secret_store_uses_runtime_roles_anywhere_profile(monkeypatch):
    calls = {}

    class FakeSession:
        def __init__(self, *, profile_name=None):
            calls["profile_name"] = profile_name

        def client(self, service_name, *, region_name=None):
            calls["service_name"] = service_name
            calls["region_name"] = region_name
            return object()

    def forbidden_direct_client(*args, **kwargs):
        raise AssertionError("Gmail OAuth store must use a boto3 Session/profile")

    monkeypatch.setenv("BEDROCK_AWS_PROFILE", "ai-recruiter-bedrock")
    monkeypatch.setattr(gmail_oauth_store.boto3, "Session", FakeSession)
    monkeypatch.setattr(gmail_oauth_store.boto3, "client", forbidden_direct_client)

    store = gmail_oauth_store.GmailOAuthSecretStore(
        "/ai-recruiter/prod/gmail-oauth"
    )

    assert store.secret_id == "/ai-recruiter/prod/gmail-oauth"
    assert calls == {
        "profile_name": "ai-recruiter-bedrock",
        "service_name": "secretsmanager",
        "region_name": "us-east-2",
    }
