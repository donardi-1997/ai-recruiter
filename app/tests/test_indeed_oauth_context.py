"""Indeed OAuth context tests."""

from urllib.parse import parse_qs

import httpx

from app.config import IndeedSettings
from app.domains.indeed.client import IndeedClient


def settings():
    return IndeedSettings(
        enabled=True,
        client_id="client",
        client_secret="secret",
        employer_id="employer-1",
        scope="employer_access employer.hosted_job",
        source_name="Asiati Talent",
        company_name="Asiati",
        token_url="https://apis.indeed.com/oauth/v2/tokens",
        graphql_url="https://apis.indeed.com/graphql",
        request_timeout_seconds=10.0,
        careers_base_url="https://www.asiaticorp.com/jobs",
    )


def _token_form(include_employer: bool) -> dict[str, list[str]]:
    token_forms = []

    def handler(request: httpx.Request):
        if request.url.path.endswith("/tokens"):
            token_forms.append(parse_qs(request.content.decode("utf-8")))
            return httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
        return httpx.Response(200, json={"data": {"ok": True}})

    client = IndeedClient(
        settings(),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        include_employer=include_employer,
    )
    client.execute("query { ok }")
    return token_forms[0]


def test_employer_context_token_includes_employer_identifier():
    form = _token_form(include_employer=True)
    assert form["employer"] == ["employer-1"]


def test_application_context_token_omits_employer_identifier():
    form = _token_form(include_employer=False)
    assert "employer" not in form
