"""Tests for the Indeed Employers integration."""

from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import IndeedSettings
from app.db import Base
from app.domains.indeed import service
from app.domains.indeed import router as indeed_router
from app.domains.indeed.client import IndeedClient
from app.domains.indeed.exceptions import IndeedLinkNotFound, IndeedRemoteError, IndeedValidationError
from app.domains.indeed.mapper import build_job_input
from app.models import IndeedJobLink, IndeedSyncEvent, Job

VALID_DESCRIPTION = "Lead Asiati operations across Chile and grow the local business."


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


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def published_job(owner="owner-1"):
    return Job(
        title="Country Manager Chile",
        description=VALID_DESCRIPTION,
        owner_sub=owner,
        country_code="CL",
        city="Santiago",
        public_slug="country-manager-chile",
        published_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
    )


class FakeIndeedClient:
    def __init__(self):
        self.calls = []

    def execute(self, query, variables=None):
        self.calls.append((query, variables))
        if "CreateSourcedJobPostings" in query:
            return {
                "jobsIngest": {
                    "createSourcedJobPostings": {
                        "results": [
                            {
                                "jobPosting": {
                                    "sourcedPostingId": "sourced-1",
                                    "employerJobId": "employer-job-1",
                                }
                            }
                        ]
                    }
                }
            }
        if "GetIndeedJobStatus" in query:
            return {
                "node": {
                    "seats": [
                        {
                            "jobPost": {
                                "status": {
                                    "globalStatus": {
                                        "lifecycleStatus": "ACTIVE",
                                        "isIndeedApplyActive": True,
                                    },
                                    "surfaceStatuses": {
                                        "isRejected": False,
                                        "isSponsorshipRequired": False,
                                        "isMissingRequiredSponsorship": False,
                                    },
                                }
                            }
                        }
                    ]
                }
            }
        if "ExpireSourcedJobsBySourcedPostingId" in query:
            return {"jobsIngest": {"expireSourcedJobsBySourcedPostingId": {"results": []}}}
        raise AssertionError("Unexpected query")


def test_job_exposes_neutral_publication_fields():
    for field in ("country_code", "city", "employment_type", "public_slug", "published_at"):
        assert hasattr(Job, field)


def test_mapper_builds_direct_employer_job_sync_payload():
    job = Job(id="job-1", title="Country Manager Chile", description=VALID_DESCRIPTION, country_code="cl", city="Santiago", public_slug="country-manager-chile", published_at=datetime(2026, 9, 15, tzinfo=timezone.utc))
    payload = build_job_input(job, careers_base_url="https://www.asiaticorp.com/jobs", source_name="Asiati Talent", company_name="Asiati")
    posting = payload["jobPostings"][0]
    assert posting["body"]["location"] == {"country": "CL", "cityRegionPostal": "Santiago"}
    assert posting["body"]["descriptionFormatting"] == "TEXT"
    assert posting["metadata"]["jobPostingId"] == "job-1"
    assert posting["metadata"]["url"] == "https://www.asiaticorp.com/jobs/country-manager-chile"
    assert posting["metadata"]["jobSource"]["sourceType"] == "Employer"


def test_mapper_rejects_missing_required_publication_fields():
    job = Job(id="job-1", title="Incomplete", description=None, country_code=None, city=None)
    with pytest.raises(IndeedValidationError):
        build_job_input(job, careers_base_url="https://www.asiaticorp.com/jobs", source_name="Asiati Talent", company_name="Asiati")


def test_mapper_rejects_values_outside_indeed_text_limits():
    too_short = Job(id="job-1", title="Valid title", description="Too short", country_code="CL", city="Santiago")
    with pytest.raises(IndeedValidationError, match="between 30 and 20000"):
        build_job_input(too_short, careers_base_url="https://www.asiaticorp.com/jobs", source_name="Asiati Talent", company_name="Asiati")

    long_title = Job(id="job-2", title="x" * 76, description=VALID_DESCRIPTION, country_code="CL", city="Santiago")
    with pytest.raises(IndeedValidationError, match="75 characters"):
        build_job_input(long_title, careers_base_url="https://www.asiaticorp.com/jobs", source_name="Asiati Talent", company_name="Asiati")


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


def test_publish_persists_external_ids_and_success_event(db_session):
    job = published_job()
    db_session.add(job)
    db_session.commit()
    fake = FakeIndeedClient()

    result = service.publish_job(
        db_session,
        job_id=job.id,
        owner_sub="owner-1",
        client=fake,
        settings=settings(),
    )

    assert result["sourced_posting_id"] == "sourced-1"
    assert result["employer_job_id"] == "employer-job-1"
    link = db_session.query(IndeedJobLink).filter_by(job_id=job.id).one()
    assert link.sourced_posting_id == "sourced-1"
    assert link.employer_job_id == "employer-job-1"
    event = db_session.query(IndeedSyncEvent).filter_by(job_id=job.id, operation="PUBLISH").one()
    assert event.status == "SUCCEEDED"


def test_status_and_expire_use_persisted_identifiers(db_session):
    job = published_job()
    db_session.add(job)
    db_session.commit()
    fake = FakeIndeedClient()
    service.publish_job(db_session, job_id=job.id, owner_sub="owner-1", client=fake, settings=settings())

    status = service.get_job_status(
        db_session,
        job_id=job.id,
        owner_sub="owner-1",
        client=fake,
        settings=settings(),
    )
    assert status["status"]["globalStatus"]["lifecycleStatus"] == "ACTIVE"

    expired = service.expire_job(
        db_session,
        job_id=job.id,
        owner_sub="owner-1",
        client=fake,
        settings=settings(),
    )
    assert expired["status"] == "EXPIRE_REQUESTED"
    link = db_session.query(IndeedJobLink).filter_by(job_id=job.id).one()
    assert link.external_status == {"lifecycleStatus": "EXPIRE_REQUESTED"}


def test_status_requires_existing_indeed_link(db_session):
    job = published_job()
    db_session.add(job)
    db_session.commit()

    with pytest.raises(IndeedLinkNotFound):
        service.get_job_status(
            db_session,
            job_id=job.id,
            owner_sub="owner-1",
            client=FakeIndeedClient(),
            settings=settings(),
        )


def test_router_never_exposes_remote_provider_error_details():
    exc = IndeedRemoteError(
        "Indeed GraphQL error: secret provider detail token=abc123"
    )
    translated = indeed_router._translate(exc)

    assert translated.status_code == 502
    assert "secret provider detail" not in translated.detail
    assert "token=abc123" not in translated.detail
