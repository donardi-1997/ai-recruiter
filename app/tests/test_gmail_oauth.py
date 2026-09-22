from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import GmailOAuthSettings, GmailSettings, get_gmail_oauth_settings
from app.domains.candidate_ingestion import gmail_integration


class FakeStore:
    def __init__(self, payload):
        self.payload = dict(payload)
        self.writes = []

    def read(self):
        return dict(self.payload)

    def write(self, payload):
        self.payload = dict(payload)
        self.writes.append(dict(payload))


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return dict(self._payload)


class FakeHttp:
    def __init__(self):
        self.posts = []
        self.gets = []

    def post(self, url, *, data=None, headers=None):
        self.posts.append((url, data, headers))
        return FakeResponse(
            {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "expires_in": 3600,
            }
        )

    def get(self, url, *, headers=None):
        self.gets.append((url, headers))
        return FakeResponse(
            {
                "emailAddress": "recruiting@asiaticorp.com",
                "historyId": "12345",
            }
        )


def gmail_settings():
    return GmailSettings(
        enabled=True,
        client_id="",
        client_secret="",
        refresh_token="",
        user_id="me",
        query="from:indeed.com has:attachment",
        allowed_senders=(),
        ingestion_provider="INDEED",
        scope="https://www.googleapis.com/auth/gmail.readonly",
        token_url="https://oauth2.googleapis.com/token",
        api_base_url="https://gmail.googleapis.com/gmail/v1",
        request_timeout_seconds=15.0,
    )


def oauth_settings():
    return GmailOAuthSettings(
        secret_id="/ai-recruiter/prod/gmail-oauth",
        redirect_uri=(
            "https://abc123.execute-api.us-east-2.amazonaws.com/prod/"
            "api/integrations/gmail/oauth/callback"
        ),
        frontend_return_url="http://3.23.27.223/integrations",
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        state_max_age_seconds=600,
    )


def oauth_secret():
    return {
        "client_id": "google-client-id",
        "client_secret": "google-client-secret",
        "refresh_token": "",
        "connected_email": "",
        "state_secret": "state-signing-secret",
        "authorized_owner_sub": "owner-a",
    }


def test_oauth_start_builds_offline_readonly_authorization_url():
    store = FakeStore(oauth_secret())

    result = gmail_integration.oauth_start(
        owner_sub="owner-a",
        settings=gmail_settings(),
        oauth_settings=oauth_settings(),
        oauth_store=store,
    )

    parsed = urlparse(result["authorization_url"])
    query = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://accounts.google.com/o/oauth2/v2/auth"
    )
    assert query["client_id"] == ["google-client-id"]
    assert query["redirect_uri"] == [oauth_settings().redirect_uri]
    assert query["response_type"] == ["code"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["include_granted_scopes"] == ["true"]
    assert query["scope"] == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert query["state"][0]
    assert "google-client-secret" not in result["authorization_url"]


def test_oauth_redirect_uri_can_be_managed_in_secret_without_container_restart():
    store_payload = oauth_secret()
    store_payload["redirect_uri"] = (
        "https://regional.execute-api.us-east-2.amazonaws.com/"
        "api/integrations/gmail/oauth/callback"
    )
    store = FakeStore(store_payload)
    settings_without_redirect = replace(oauth_settings(), redirect_uri="")

    result = gmail_integration.oauth_start(
        owner_sub="owner-a",
        settings=gmail_settings(),
        oauth_settings=settings_without_redirect,
        oauth_store=store,
    )
    query = parse_qs(urlparse(result["authorization_url"]).query)
    status = gmail_integration.integration_status(
        owner_sub="owner-a",
        settings=gmail_settings(),
        oauth_settings=settings_without_redirect,
        oauth_store=store,
    )

    assert query["redirect_uri"] == [store_payload["redirect_uri"]]
    assert status["redirect_uri"] == store_payload["redirect_uri"]
    assert status["oauth_configured"] is True


def test_oauth_callback_validates_state_and_persists_refresh_token_and_mailbox():
    store = FakeStore(oauth_secret())
    http = FakeHttp()
    start = gmail_integration.oauth_start(
        owner_sub="owner-a",
        settings=gmail_settings(),
        oauth_settings=oauth_settings(),
        oauth_store=store,
    )
    state = parse_qs(urlparse(start["authorization_url"]).query)["state"][0]

    result = gmail_integration.oauth_callback(
        code="authorization-code",
        state=state,
        settings=gmail_settings(),
        oauth_settings=oauth_settings(),
        oauth_store=store,
        http_client=http,
    )

    assert result == {
        "connected": True,
        "connected_email": "recruiting@asiaticorp.com",
    }
    assert store.payload["client_id"] == "google-client-id"
    assert store.payload["client_secret"] == "google-client-secret"
    assert store.payload["refresh_token"] == "refresh-token"
    assert store.payload["connected_email"] == "recruiting@asiaticorp.com"
    assert store.payload["state_secret"] == "state-signing-secret"
    assert store.payload["connected_by_sub"] == "owner-a"

    token_url, token_data, _ = http.posts[0]
    assert token_url == "https://oauth2.googleapis.com/token"
    assert token_data["code"] == "authorization-code"
    assert token_data["redirect_uri"] == oauth_settings().redirect_uri
    assert token_data["client_secret"] == "google-client-secret"


def test_oauth_callback_rejects_tampered_state_before_token_exchange():
    store = FakeStore(oauth_secret())
    http = FakeHttp()

    with pytest.raises(gmail_integration.GmailOAuthStateError):
        gmail_integration.oauth_callback(
            code="authorization-code",
            state="tampered-state",
            settings=gmail_settings(),
            oauth_settings=oauth_settings(),
            oauth_store=store,
            http_client=http,
        )

    assert http.posts == []


def test_status_exposes_connection_metadata_but_never_oauth_secrets():
    connected = oauth_secret()
    connected["refresh_token"] = "refresh-token"
    connected["connected_email"] = "recruiting@asiaticorp.com"
    store = FakeStore(connected)

    status = gmail_integration.integration_status(
        owner_sub="owner-a",
        settings=gmail_settings(),
        oauth_settings=oauth_settings(),
        oauth_store=store,
    )

    assert status == {
        "enabled": True,
        "configured": True,
        "oauth_configured": True,
        "connected": True,
        "connected_email": "recruiting@asiaticorp.com",
        "manageable": True,
        "provider": "INDEED",
        "safe_filter": True,
        "redirect_uri": oauth_settings().redirect_uri,
    }
    serialized = repr(status).casefold()
    assert "google-client-secret" not in serialized
    assert "refresh-token" not in serialized


def test_disconnect_clears_mailbox_tokens_but_preserves_oauth_client():
    connected = oauth_secret()
    connected["refresh_token"] = "refresh-token"
    connected["connected_email"] = "recruiting@asiaticorp.com"
    store = FakeStore(connected)

    result = gmail_integration.disconnect_oauth(
        owner_sub="owner-a",
        oauth_store=store,
    )

    assert result == {"connected": False}
    assert store.payload["client_id"] == "google-client-id"
    assert store.payload["client_secret"] == "google-client-secret"
    assert store.payload["state_secret"] == "state-signing-secret"
    assert store.payload["refresh_token"] == ""
    assert store.payload["connected_email"] == ""


def test_oauth_frontend_return_defaults_to_cloudfront(monkeypatch):
    monkeypatch.delenv("GMAIL_OAUTH_FRONTEND_RETURN_URL", raising=False)

    settings = get_gmail_oauth_settings()

    assert settings.frontend_return_url == (
        "https://dzcwl3yhv133t.cloudfront.net/integrations"
    )


def test_oauth_start_rejects_non_owner():
    store = FakeStore(oauth_secret())

    with pytest.raises(gmail_integration.GmailOAuthOwnershipError):
        gmail_integration.oauth_start(
            owner_sub="owner-b",
            settings=gmail_settings(),
            oauth_settings=oauth_settings(),
            oauth_store=store,
        )


def test_disconnect_rejects_non_owner():
    connected = oauth_secret()
    connected["refresh_token"] = "refresh-token"
    connected["connected_email"] = "recruiting@asiaticorp.com"
    connected["connected_by_sub"] = "owner-a"
    store = FakeStore(connected)

    with pytest.raises(gmail_integration.GmailOAuthOwnershipError):
        gmail_integration.disconnect_oauth(
            owner_sub="owner-b",
            oauth_store=store,
        )

    assert store.payload["refresh_token"] == "refresh-token"


def test_unowned_existing_mailbox_can_only_be_claimed_with_same_google_account():
    payload = oauth_secret()
    payload.pop("authorized_owner_sub")
    payload["refresh_token"] = "legacy-refresh"
    payload["connected_email"] = "recruiting@asiaticorp.com"
    store = FakeStore(payload)
    http = FakeHttp()

    start = gmail_integration.oauth_start(
        owner_sub="owner-a",
        settings=gmail_settings(),
        oauth_settings=oauth_settings(),
        oauth_store=store,
    )
    state = parse_qs(urlparse(start["authorization_url"]).query)["state"][0]

    gmail_integration.oauth_callback(
        code="authorization-code",
        state=state,
        settings=gmail_settings(),
        oauth_settings=oauth_settings(),
        oauth_store=store,
        http_client=http,
    )

    assert store.payload["connected_by_sub"] == "owner-a"


def test_new_unowned_oauth_configuration_cannot_be_claimed_by_arbitrary_user():
    payload = oauth_secret()
    payload.pop("authorized_owner_sub")
    store = FakeStore(payload)

    with pytest.raises(gmail_integration.GmailOAuthOwnershipError):
        gmail_integration.oauth_start(
            owner_sub="owner-a",
            settings=gmail_settings(),
            oauth_settings=oauth_settings(),
            oauth_store=store,
        )
