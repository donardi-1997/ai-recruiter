from app.config import GmailOAuthSettings, GmailSettings
from app.domains.candidate_ingestion import gmail_integration


class FakeStore:
    def __init__(self, payload):
        self.payload = dict(payload)

    def read(self):
        return dict(self.payload)


def test_status_reports_missing_oauth_fields_without_exposing_secret_values():
    settings = GmailSettings(
        enabled=True,
        client_id="",
        client_secret="",
        refresh_token="",
        user_id="me",
        query="has:attachment",
        allowed_senders=(),
        ingestion_provider="INDEED",
        scope="https://www.googleapis.com/auth/gmail.readonly",
        token_url="https://oauth2.googleapis.com/token",
        api_base_url="https://gmail.googleapis.com/gmail/v1",
        request_timeout_seconds=15.0,
    )
    oauth = GmailOAuthSettings(
        secret_id="/ai-recruiter/prod/gmail-oauth",
        redirect_uri="",
        frontend_return_url="http://3.23.27.223/integrations",
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        state_max_age_seconds=600,
    )
    store = FakeStore(
        {
            "client_id": "",
            "client_secret": "",
            "state_secret": "present-state-secret",
            "redirect_uri": "https://3fkmecjfig.execute-api.us-east-2.amazonaws.com/api/integrations/gmail/oauth/callback",
        }
    )

    status = gmail_integration.integration_status(
        settings=settings,
        oauth_settings=oauth,
        oauth_store=store,
    )

    assert status["oauth_configured"] is False
    assert status["oauth_missing"] == ["client_id", "client_secret"]
    assert "present-state-secret" not in repr(status)
