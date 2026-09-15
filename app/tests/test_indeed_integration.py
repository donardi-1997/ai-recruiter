"""Tests for the Indeed Employers integration."""

from datetime import datetime, timezone

import httpx
import pytest

from app.config import IndeedSettings
from app.domains.indeed.client import IndeedClient
from app.domains.indeed.exceptions import IndeedRemoteError, IndeedValidationError
from app.domains.indeed.mapper import build_job_input
from app.models import Job


def settings(**overrides):
    values = dict(
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
    values.update(overrides)
    return IndeedSettings(**values)


def test_job_exposes_neutral_publication_fields():
    for field in ("country_code", "city", "employment_type", "public_slug", "published_at"):
        assert hasattr(Job, field)


def test_mapper_builds_direct_employer_job_sync_payload():
    job = Job(id="job-1", title="Country Manager Chile", description="Lead the operation", country_code="cl", city="Santiago", public_slug="country-manager-chile", published_at=datetime(2026, 9, 15, tzinfo=timezone.utc))
    payload = build_job_input(job, careers_base_url="https://www.asiaticorp.com/jobs", source_name="Asiati Talent", company_name="Asiati")
    posting = payload["jobPostings"][0]
    assert posting["body"]["location"] == {"country": "CL", "cityRegionPostal": "Santiago"}
    assert posting["metadata"]["jobPostingId"] == "job-1"
    assert posting["metadata"]["url"] == "https://www.asiaticorp.com/jobs/country-manager-chile"
    assert posting["metadata"]["jobSource"]["sourceType"] == "Employer"


def test_mapper_rejects_missing_required_publication_fields():
    job = Job(id="job-1", title="Incomplete", description=None, country_code=None, city=None)
    with pytest.raises(IndeedValidationError):
        build_job_input(job, careers_base_url="https://www.asiaticorp.com/jobs", source_name="Asiati Talent", company_name="Asiati")


def test_client_caches_oauth_token_and_sends_bearer_header():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        if request.url.path.endswith("/tokens"):
            return httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer token-123"
        return httpx.Response(200, json={"data": {"ok": True}})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = IndeedClient(settings(), http=http)
    assert client.execute("query { ok }") == {"ok": True}
    assert client.execute("query { ok }") == {"ok": True}
    assert sum(1 for request in requests if request.url.path.endswith("/tokens")) == 1


def test_client_raises_typed_error_for_graphql_errors():
    def handler(request: httpx.Request):
        if request.url.path.endswith("/tokens"):
            return httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
        return httpx.Response(200, json={"errors": [{"message": "FORBIDDEN"}]})

    client = IndeedClient(settings(), http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(IndeedRemoteError, match="FORBIDDEN"):
        client.execute("query { nope }")
