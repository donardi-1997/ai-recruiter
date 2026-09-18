"""Contracts for the configurable Gmail mailbox transport."""

import importlib

import pytest

import app.config as config


class FakeResponse:
    def __init__(self, payload, *, status_code=200, content=b"", headers=None):
        self._payload = payload
        self.status_code = status_code
        self.content = content
        self.headers = dict(headers or {})

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpClient:
    def __init__(self):
        self.posts = []
        self.gets = []
        self.post_response = FakeResponse({"access_token": "access-1", "expires_in": 3600})
        self.get_responses = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return self.post_response

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        if not self.get_responses:
            raise AssertionError(f"unexpected GET {url}")
        return self.get_responses.pop(0)


def _module():
    try:
        return importlib.import_module("app.integrations.email_ingestion.gmail")
    except ModuleNotFoundError as exc:
        pytest.fail(f"gmail transport is missing: {exc}")


def _settings(monkeypatch):
    monkeypatch.setenv("GMAIL_ENABLED", "true")
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("GMAIL_USER_ID", "me")
    monkeypatch.setenv("GMAIL_QUERY", "has:attachment")
    return config.get_gmail_settings()


def test_refresh_access_token_uses_oauth_refresh_token_not_mailbox_password(monkeypatch):
    gmail = _module()
    fake = FakeHttpClient()
    client = gmail.GmailClient(_settings(monkeypatch), http_client=fake)

    token = client.refresh_access_token()

    assert token == "access-1"
    url, request = fake.posts[0]
    assert url == "https://oauth2.googleapis.com/token"
    assert request["data"] == {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "refresh_token": "refresh-token",
        "grant_type": "refresh_token",
    }
    assert "password" not in request["data"]


def test_list_messages_uses_authenticated_configured_mailbox_and_query(monkeypatch):
    gmail = _module()
    fake = FakeHttpClient()
    fake.get_responses = [
        FakeResponse(
            {
                "messages": [
                    {"id": "gmail-1", "threadId": "thread-1"},
                    {"id": "gmail-2", "threadId": "thread-2"},
                ],
                "nextPageToken": "next-1",
            }
        )
    ]
    client = gmail.GmailClient(_settings(monkeypatch), http_client=fake)
    monkeypatch.setattr(client, "get_access_token", lambda: "access-1")

    result = client.list_messages(page_token="page-1", max_results=25)

    assert [item["id"] for item in result.messages] == ["gmail-1", "gmail-2"]
    assert result.next_page_token == "next-1"
    url, request = fake.gets[0]
    assert url == "https://gmail.googleapis.com/gmail/v1/users/me/messages"
    assert request["headers"] == {"Authorization": "Bearer access-1"}
    assert request["params"] == {
        "q": "has:attachment",
        "maxResults": 25,
        "pageToken": "page-1",
    }


def test_get_message_and_attachment_use_google_message_ids(monkeypatch):
    gmail = _module()
    fake = FakeHttpClient()
    fake.get_responses = [
        FakeResponse({"id": "gmail-1", "historyId": "55", "payload": {"parts": []}}),
        FakeResponse({"data": "aGVsbG8"}),
    ]
    client = gmail.GmailClient(_settings(monkeypatch), http_client=fake)
    monkeypatch.setattr(client, "get_access_token", lambda: "access-1")

    message = client.get_message("gmail-1")
    attachment = client.get_attachment("gmail-1", "attachment-1")

    assert message["historyId"] == "55"
    assert attachment == b"hello"
    assert fake.gets[0][0].endswith("/users/me/messages/gmail-1")
    assert fake.gets[0][1]["params"] == {"format": "full"}
    assert fake.gets[1][0].endswith(
        "/users/me/messages/gmail-1/attachments/attachment-1"
    )


def test_refresh_access_token_classifies_rejected_refresh_without_exposing_payload(monkeypatch):
    gmail = _module()
    fake = FakeHttpClient()
    fake.post_response = FakeResponse(
        {"error": "invalid_grant", "error_description": "sensitive remote detail"},
        status_code=400,
    )
    client = gmail.GmailClient(_settings(monkeypatch), http_client=fake)

    with pytest.raises(gmail.GmailTokenRefreshRejected) as exc:
        client.refresh_access_token()

    assert str(exc.value) == "GMAIL_TOKEN_REFRESH_REJECTED"
    assert "sensitive remote detail" not in str(exc.value)


def test_gmail_profile_classifies_permission_denied_without_response_body(monkeypatch):
    gmail = _module()
    fake = FakeHttpClient()
    fake.get_responses = [
        FakeResponse(
            {
                "error": {
                    "message": "sensitive permission detail",
                    "errors": [{"reason": "insufficientPermissions"}],
                    "status": "PERMISSION_DENIED",
                }
            },
            status_code=403,
        )
    ]
    client = gmail.GmailClient(_settings(monkeypatch), http_client=fake)
    monkeypatch.setattr(client, "get_access_token", lambda: "access-1")

    with pytest.raises(gmail.GmailApiPermissionDenied) as exc:
        client.get_profile()

    assert str(exc.value) == (
        "GMAIL_API_PERMISSION_DENIED:get_profile:insufficientPermissions"
    )
    assert "sensitive permission detail" not in str(exc.value)


def test_gmail_list_classifies_unauthorized(monkeypatch):
    gmail = _module()
    fake = FakeHttpClient()
    fake.get_responses = [FakeResponse({"error": "invalid_token"}, status_code=401)]
    client = gmail.GmailClient(_settings(monkeypatch), http_client=fake)
    monkeypatch.setattr(client, "get_access_token", lambda: "access-1")

    with pytest.raises(gmail.GmailApiUnauthorized) as exc:
        client.list_messages()

    assert str(exc.value) == "GMAIL_API_UNAUTHORIZED:list_messages:UNKNOWN"


def test_gmail_permission_denied_identifies_list_messages_operation(monkeypatch):
    gmail = _module()
    fake = FakeHttpClient()
    fake.get_responses = [
        FakeResponse(
            {
                "error": {
                    "message": "do not expose this message",
                    "errors": [{"reason": "accessNotConfigured"}],
                }
            },
            status_code=403,
        )
    ]
    client = gmail.GmailClient(_settings(monkeypatch), http_client=fake)
    monkeypatch.setattr(client, "get_access_token", lambda: "access-1")

    with pytest.raises(gmail.GmailApiPermissionDenied) as exc:
        client.list_messages()

    assert str(exc.value) == (
        "GMAIL_API_PERMISSION_DENIED:list_messages:accessNotConfigured"
    )
    assert "do not expose this message" not in str(exc.value)


def test_gmail_rate_limit_retries_then_succeeds(monkeypatch):
    gmail = _module()
    fake = FakeHttpClient()
    fake.get_responses = [
        FakeResponse(
            {"error": {"errors": [{"reason": "rateLimitExceeded"}]}},
            status_code=403,
        ),
        FakeResponse(
            {"id": "gmail-1", "historyId": "55", "payload": {"parts": []}},
            status_code=200,
        ),
    ]
    sleeps = []
    client = gmail.GmailClient(
        _settings(monkeypatch),
        http_client=fake,
        sleep_fn=sleeps.append,
        jitter_fn=lambda: 0.0,
    )
    monkeypatch.setattr(client, "get_access_token", lambda: "access-1")

    message = client.get_message("gmail-1")

    assert message["id"] == "gmail-1"
    assert len(fake.gets) == 2
    assert sleeps == [1.0]


def test_gmail_rate_limit_honors_retry_after(monkeypatch):
    gmail = _module()
    fake = FakeHttpClient()
    fake.get_responses = [
        FakeResponse(
            {"error": {"errors": [{"reason": "userRateLimitExceeded"}]}},
            status_code=403,
            headers={"Retry-After": "3"},
        ),
        FakeResponse({"emailAddress": "user@gmail.com", "historyId": "123"}),
    ]
    sleeps = []
    client = gmail.GmailClient(
        _settings(monkeypatch),
        http_client=fake,
        sleep_fn=sleeps.append,
        jitter_fn=lambda: 0.0,
    )
    monkeypatch.setattr(client, "get_access_token", lambda: "access-1")

    profile = client.get_profile()

    assert profile.email_address == "user@gmail.com"
    assert sleeps == [3.0]


def test_gmail_rate_limit_remains_classified_after_bounded_retries(monkeypatch):
    gmail = _module()
    fake = FakeHttpClient()
    fake.get_responses = [
        FakeResponse(
            {"error": {"errors": [{"reason": "rateLimitExceeded"}]}},
            status_code=403,
        )
        for _ in range(4)
    ]
    sleeps = []
    client = gmail.GmailClient(
        _settings(monkeypatch),
        http_client=fake,
        sleep_fn=sleeps.append,
        jitter_fn=lambda: 0.0,
    )
    monkeypatch.setattr(client, "get_access_token", lambda: "access-1")

    with pytest.raises(gmail.GmailApiPermissionDenied) as exc:
        client.get_message("gmail-1")

    assert str(exc.value) == (
        "GMAIL_API_PERMISSION_DENIED:get_message:rateLimitExceeded"
    )
    assert len(fake.gets) == 4
    assert sleeps == [1.0, 2.0, 4.0]
