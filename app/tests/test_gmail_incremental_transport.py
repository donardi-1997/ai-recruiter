"""Contracts for Gmail mailbox identity and incremental history transport."""

import app.config as config
from app.integrations.email_ingestion.gmail import GmailClient


class FakeResponse:
    def __init__(self, payload, *, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.gets = []

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return self.responses.pop(0)


def _settings(monkeypatch):
    monkeypatch.setenv("GMAIL_ENABLED", "true")
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh-token")
    return config.get_gmail_settings()


def test_get_profile_discovers_authorized_mailbox_identity(monkeypatch):
    fake = FakeHttpClient(
        [FakeResponse({"emailAddress": "personal@example.com", "historyId": "100"})]
    )
    client = GmailClient(_settings(monkeypatch), http_client=fake)
    monkeypatch.setattr(client, "get_access_token", lambda: "access-1")

    profile = client.get_profile()

    assert profile.email_address == "personal@example.com"
    assert profile.history_id == "100"
    assert fake.gets[0][0].endswith("/users/me/profile")


def test_list_history_returns_added_message_ids_and_next_cursor(monkeypatch):
    fake = FakeHttpClient(
        [
            FakeResponse(
                {
                    "history": [
                        {
                            "id": "101",
                            "messagesAdded": [
                                {"message": {"id": "gmail-2", "threadId": "thread-2"}},
                                {"message": {"id": "gmail-3", "threadId": "thread-3"}},
                            ],
                        },
                        {
                            "id": "102",
                            "messagesAdded": [
                                {"message": {"id": "gmail-2", "threadId": "thread-2"}}
                            ],
                        },
                    ],
                    "historyId": "120",
                    "nextPageToken": "next-1",
                }
            )
        ]
    )
    client = GmailClient(_settings(monkeypatch), http_client=fake)
    monkeypatch.setattr(client, "get_access_token", lambda: "access-1")

    result = client.list_history(start_history_id="100", page_token="page-1")

    assert result.message_ids == ("gmail-2", "gmail-3")
    assert result.history_id == "120"
    assert result.next_page_token == "next-1"
    url, request = fake.gets[0]
    assert url.endswith("/users/me/history")
    assert request["params"] == {
        "startHistoryId": "100",
        "historyTypes": "messageAdded",
        "labelId": "INBOX",
        "maxResults": 100,
        "pageToken": "page-1",
    }
