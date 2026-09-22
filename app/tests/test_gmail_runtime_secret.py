from app.config import GmailOAuthSettings, GmailSettings
from app.domains.candidate_ingestion import gmail_integration
from app.domains.candidate_ingestion.mailbox_sync import GmailMailboxSyncResult


class FakeStore:
    def __init__(self, payload):
        self.payload = dict(payload)

    def read(self):
        return dict(self.payload)

    def write(self, payload):
        self.payload = dict(payload)


def disabled_env_settings():
    return GmailSettings(
        enabled=False,
        client_id="",
        client_secret="",
        refresh_token="",
        user_id="me",
        query="has:attachment",
        allowed_senders=(),
        ingestion_provider="GENERIC",
        scope="https://www.googleapis.com/auth/gmail.readonly",
        token_url="https://oauth2.googleapis.com/token",
        api_base_url="https://gmail.googleapis.com/gmail/v1",
        request_timeout_seconds=15.0,
    )


def oauth_settings():
    return GmailOAuthSettings(
        secret_id="/ai-recruiter/prod/gmail-oauth",
        redirect_uri="",
        frontend_return_url="http://3.23.27.223/integrations",
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        state_max_age_seconds=600,
    )


def runtime_secret():
    return {
        "client_id": "google-client-id",
        "client_secret": "google-client-secret",
        "refresh_token": "refresh-token",
        "connected_email": "recruiting@asiaticorp.com",
        "state_secret": "state-signing-secret",
        "authorized_owner_sub": "owner-a",
        "redirect_uri": (
            "https://regional.execute-api.us-east-2.amazonaws.com/"
            "api/integrations/gmail/oauth/callback"
        ),
        "enabled": True,
        "query": "from:indeedemail.com",
        "allowed_senders": [],
        "ingestion_provider": "INDEED",
    }


def test_status_resolves_operational_configuration_from_secret():
    status = gmail_integration.integration_status(
        settings=disabled_env_settings(),
        oauth_settings=oauth_settings(),
        oauth_store=FakeStore(runtime_secret()),
    )

    assert status["enabled"] is True
    assert status["configured"] is True
    assert status["oauth_configured"] is True
    assert status["safe_filter"] is True
    assert status["provider"] == "INDEED"
    assert status["redirect_uri"] == runtime_secret()["redirect_uri"]


def test_runtime_secret_uses_link_discovery_not_attachment_filter():
    secret = runtime_secret()
    assert secret["query"] == "from:indeedemail.com"
    assert secret["allowed_senders"] == []
    assert "has:attachment" not in secret["query"]


def test_sync_uses_operational_configuration_from_secret(monkeypatch):
    captured = {}

    def fake_sync(
        db,
        *,
        owner_sub,
        provider,
        mailbox_client,
        allowed_senders,
        allowed_sender_domains,
        storage,
    ):
        captured.update(
            {
                "owner_sub": owner_sub,
                "provider": provider,
                "allowed_senders": allowed_senders,
                "allowed_sender_domains": allowed_sender_domains,
            }
        )
        return GmailMailboxSyncResult(
            mode="FULL",
            source_account="recruiting@asiaticorp.com",
            discovered=0,
            created=0,
            existing=0,
            needs_review=0,
            skipped=0,
            cursor_value="123",
        )

    monkeypatch.setattr(gmail_integration, "sync_gmail_mailbox", fake_sync)

    result = gmail_integration.sync_mailbox(
        None,
        owner_sub="owner-a",
        settings=disabled_env_settings(),
        oauth_settings=oauth_settings(),
        oauth_store=FakeStore(runtime_secret()),
        mailbox_client=object(),
    )

    assert result["mode"] == "FULL"
    assert captured == {
        "owner_sub": "owner-a",
        "provider": "INDEED",
        "allowed_senders": (),
        "allowed_sender_domains": ("indeedemail.com",),
    }


def test_sender_domains_are_derived_only_from_safe_from_terms():
    assert gmail_integration._sender_domains_from_query(
        'from:indeedemail.com newer_than:7d'
    ) == ("indeedemail.com",)
    assert gmail_integration._sender_domains_from_query(
        'from:conversation@sub.indeedemail.com'
    ) == ("sub.indeedemail.com",)
    assert gmail_integration._sender_domains_from_query(
        'subject:"from:evil.example"'
    ) == ()
