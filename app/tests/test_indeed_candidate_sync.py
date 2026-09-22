"""Contract tests for Indeed Retrieve Candidates and Disposition Sync."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import IndeedSettings
from app.db import Base
from app.domains.candidate_imports.exceptions import IdentityConflict
from app.domains.candidates import service as candidate_service
from app.domains.indeed import dispositions, repository as indeed_repository, service
from app.domains.indeed.exceptions import IndeedValidationError
from app.models import (
    Candidate,
    CandidateIdentity,
    IndeedCandidateLink,
    IndeedCandidateSyncState,
    IndeedDispositionEvent,
    IndeedJobLink,
    Job,
    JobCandidate,
)


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


def seed_job(db, *, owner="owner-1", sourced="sourced-1", employer_job="employer-job-1"):
    job = Job(
        title="Country Manager Chile",
        description="Lead the Chile operation and expand Asiati in the local market.",
        owner_sub=owner,
        country_code="CL",
        city="Santiago",
        public_slug="country-manager-chile",
    )
    db.add(job)
    db.flush()
    db.add(
        IndeedJobLink(
            job_id=job.id,
            owner_sub=owner,
            sourced_posting_id=sourced,
            employer_job_id=employer_job,
        )
    )
    db.commit()
    return job


def interested_asset(
    *,
    asset_id="asset-1",
    sourced="sourced-1",
    email="ana@example.com",
    phone="+573001112233",
    name="Ana Perez",
):
    return {
        "id": asset_id,
        "metadata": {
            "stagedAt": "2026-09-15T20:00:00Z",
            "stagedTest": True,
            "employerIdentifier": "asiati",
            "completeSourceAttribution": {
                "enumKey": "INDEED_SMART_SOURCING",
                "name": "Indeed Smart Sourcing",
            },
        },
        "contact": {
            "candidate": {
                "email": email,
                "location": "Santiago, Chile",
                "name": name,
                "phone": phone,
                "resume": {
                    "pdf": {
                        "name": "ana-perez.pdf",
                        "url": "https://example.invalid/private-resume",
                    }
                },
            },
            "job": {"sourcedPostingId": sourced},
            "tracking": {"recruiterEmail": "recruiter@asiati.com"},
        },
    }


class CandidateSyncClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def execute(self, query, variables=None):
        assert "FetchAssets" in query
        self.calls.append(variables or {})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def fetch_response(assets, token):
    return {
        "atsSyncCandidateSync": {
            "fetchAssets": {
                "assets": assets,
                "token": token,
            }
        }
    }


def test_candidate_sync_creates_candidate_assignment_link_and_new_disposition(db_session):
    job = seed_job(db_session)
    fake = CandidateSyncClient([fetch_response([interested_asset()], "ack-1")])

    result = service.sync_candidates(
        db_session,
        owner_sub="owner-1",
        client=fake,
        settings=settings(),
    )

    assert result == {
        "fetched": 1,
        "created": 1,
        "reused": 0,
        "skipped": 0,
        "next_token_present": True,
        "last_sync_at": result["last_sync_at"],
    }
    candidate = db_session.query(Candidate).one()
    assert candidate.email == "ana@example.com"
    assert candidate.metadata_["source"] == "Indeed"
    assert candidate.metadata_["source_name"] == "Indeed Smart Sourcing"
    assert candidate.metadata_["resume_name"] == "ana-perez.pdf"

    assignment = db_session.query(JobCandidate).one()
    assert assignment.job_id == job.id
    assert assignment.application_status == "APPLIED"

    link = db_session.query(IndeedCandidateLink).one()
    assert link.asset_id == "asset-1"
    assert link.source_name == "Indeed Smart Sourcing"
    assert link.resume_url == "https://example.invalid/private-resume"
    assert link.acknowledged_at is None

    event = db_session.query(IndeedDispositionEvent).one()
    assert event.local_status == "APPLIED"
    assert event.indeed_status == "NEW"
    assert event.sync_status == "PENDING"


def test_same_candidate_across_two_jobs_reuses_candidate_and_creates_two_assignments(db_session):
    first_job = seed_job(
        db_session,
        sourced="sourced-1",
        employer_job="employer-job-1",
    )
    second_job = seed_job(
        db_session,
        sourced="sourced-2",
        employer_job="employer-job-2",
    )
    first = interested_asset(
        asset_id="asset-1",
        sourced="sourced-1",
        email="ana@example.com",
        phone="+573001112233",
        name="Ana Perez",
    )
    second = interested_asset(
        asset_id="asset-2",
        sourced="sourced-2",
        email="ana@example.com",
        phone="+573001112233",
        name="Ana Perez",
    )
    fake = CandidateSyncClient([fetch_response([first, second], None)])

    result = service.sync_candidates(
        db_session,
        owner_sub="owner-1",
        client=fake,
        settings=settings(),
    )

    assert result["created"] == 1
    assert result["reused"] == 1
    assert db_session.query(Candidate).count() == 1
    assignments = db_session.query(JobCandidate).all()
    assert len(assignments) == 2
    assert {item.job_id for item in assignments} == {first_job.id, second_job.id}
    assert len({item.candidate_id for item in assignments}) == 1
    assert db_session.query(IndeedCandidateLink).count() == 2


def test_duplicate_application_same_candidate_same_job_uses_latest_link(db_session):
    job = seed_job(db_session)
    old = interested_asset(
        asset_id="asset-old",
        sourced="sourced-1",
        email="ana@example.com",
        phone="+573001112233",
        name="Ana Perez",
    )
    old["metadata"]["stagedAt"] = "2026-05-01T10:00:00Z"
    new = interested_asset(
        asset_id="asset-new",
        sourced="sourced-1",
        email="ana@example.com",
        phone="+573001112233",
        name="Ana Perez",
    )
    new["metadata"]["stagedAt"] = "2026-09-20T10:00:00Z"
    fake = CandidateSyncClient([fetch_response([old, new], None)])

    service.sync_candidates(
        db_session,
        owner_sub="owner-1",
        client=fake,
        settings=settings(),
    )

    candidate = db_session.query(Candidate).one()
    assert db_session.query(JobCandidate).count() == 1
    assert db_session.query(IndeedCandidateLink).count() == 2

    active_link = indeed_repository.get_candidate_link(
        db_session,
        owner_sub="owner-1",
        job_id=job.id,
        candidate_id=candidate.id,
    )

    assert active_link is not None
    assert active_link.asset_id == "asset-new"
    assert active_link.staged_at is not None
    assert active_link.staged_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 9, 20, 10, 0, tzinfo=timezone.utc
    )


def test_candidate_sync_acknowledges_previous_batch_on_next_fetch(db_session):
    seed_job(db_session)
    fake = CandidateSyncClient(
        [
            fetch_response([interested_asset()], "ack-1"),
            fetch_response([], None),
        ]
    )

    service.sync_candidates(db_session, owner_sub="owner-1", client=fake, settings=settings())
    first_link = db_session.query(IndeedCandidateLink).one()
    assert first_link.acknowledged_at is None

    second = service.sync_candidates(db_session, owner_sub="owner-1", client=fake, settings=settings())
    db_session.refresh(first_link)
    state = db_session.query(IndeedCandidateSyncState).filter_by(owner_sub="owner-1").one()

    assert fake.calls[1]["input"]["token"] == "ack-1"
    assert first_link.acknowledged_at is not None
    assert state.ack_token is None
    assert state.last_ack_at is not None
    assert second["fetched"] == 0


def test_candidate_sync_is_idempotent_by_asset_id(db_session):
    seed_job(db_session)
    asset = interested_asset()
    fake = CandidateSyncClient(
        [
            fetch_response([asset], "ack-1"),
            fetch_response([asset], "ack-2"),
        ]
    )

    service.sync_candidates(db_session, owner_sub="owner-1", client=fake, settings=settings())
    result = service.sync_candidates(db_session, owner_sub="owner-1", client=fake, settings=settings())

    assert result["reused"] == 1
    assert db_session.query(Candidate).count() == 1
    assert db_session.query(IndeedCandidateLink).count() == 1
    assert db_session.query(IndeedDispositionEvent).count() == 1


def test_unknown_asset_or_unknown_job_is_skipped_without_candidate(db_session):
    seed_job(db_session)
    unknown_type = {"id": "asset-unknown", "metadata": {"stagedTest": True}}
    wrong_job = interested_asset(asset_id="asset-2", sourced="not-our-job")
    fake = CandidateSyncClient([fetch_response([unknown_type, wrong_job], None)])

    result = service.sync_candidates(
        db_session,
        owner_sub="owner-1",
        client=fake,
        settings=settings(),
    )

    assert result["skipped"] == 2
    assert db_session.query(Candidate).count() == 0
    assert db_session.query(IndeedCandidateLink).count() == 0


def test_failed_candidate_batch_does_not_advance_ack_token(db_session):
    seed_job(db_session)
    first = Candidate(name="Existing email", email="ana@example.com", owner_sub="owner-1")
    second = Candidate(name="Existing phone", email="other@example.com", owner_sub="owner-1")
    db_session.add_all([first, second])
    db_session.flush()
    db_session.add_all(
        [
            CandidateIdentity(owner_sub="owner-1", candidate_id=first.id, kind="EMAIL", value="ana@example.com"),
            CandidateIdentity(owner_sub="owner-1", candidate_id=second.id, kind="PHONE", value="+573001112233"),
        ]
    )
    db_session.commit()
    fake = CandidateSyncClient([fetch_response([interested_asset()], "must-not-persist")])

    with pytest.raises(IdentityConflict):
        service.sync_candidates(
            db_session,
            owner_sub="owner-1",
            client=fake,
            settings=settings(),
        )

    state = db_session.query(IndeedCandidateSyncState).filter_by(owner_sub="owner-1").one()
    assert state.ack_token is None
    assert state.last_error
    assert db_session.query(IndeedCandidateLink).count() == 0


def seed_indeed_candidate(db, *, apply_id=None, ittk=None, universal=None):
    job = seed_job(db)
    candidate = Candidate(name="Ana Perez", email="ana@example.com", owner_sub="owner-1")
    db.add(candidate)
    db.flush()
    assignment = JobCandidate(job_id=job.id, candidate_id=candidate.id)
    db.add(assignment)
    db.flush()
    link = IndeedCandidateLink(
        owner_sub="owner-1",
        candidate_id=candidate.id,
        job_id=job.id,
        asset_id="asset-1",
        source_name="Indeed",
        sourced_posting_id="sourced-1",
        indeed_apply_id=apply_id,
        ittk=ittk,
        universal_apply_id=universal,
    )
    db.add(link)
    db.commit()
    return job, candidate, assignment, link


def test_application_status_change_queues_disposition_and_duplicate_is_noop(db_session):
    job, candidate, assignment, _link = seed_indeed_candidate(db_session)

    updated, changed = candidate_service.set_application_status(
        db_session,
        job_id=job.id,
        candidate_id=candidate.id,
        status="INTERVIEW",
        owner_sub="owner-1",
    )
    assert changed is True
    assert updated.application_status == "INTERVIEW"
    event = db_session.query(IndeedDispositionEvent).one()
    assert event.indeed_status == "INTERVIEW"

    same, changed_again = candidate_service.set_application_status(
        db_session,
        job_id=job.id,
        candidate_id=candidate.id,
        status="INTERVIEW",
        owner_sub="owner-1",
    )
    assert same.id == assignment.id
    assert changed_again is False
    assert db_session.query(IndeedDispositionEvent).count() == 1


def test_on_hold_has_no_outbound_disposition_and_invalid_status_is_rejected(db_session):
    job, candidate, _assignment, _link = seed_indeed_candidate(db_session)

    _link_state, changed = candidate_service.set_application_status(
        db_session,
        job_id=job.id,
        candidate_id=candidate.id,
        status="ON_HOLD",
        owner_sub="owner-1",
    )
    assert changed is True
    assert db_session.query(IndeedDispositionEvent).count() == 0

    from app.domains.candidates.exceptions import InvalidApplicationStatus

    with pytest.raises(InvalidApplicationStatus):
        candidate_service.set_application_status(
            db_session,
            job_id=job.id,
            candidate_id=candidate.id,
            status="MAGIC_STATUS",
            owner_sub="owner-1",
        )


def test_disposition_identifier_priority_and_alternate_fallback(db_session):
    _job, _candidate, _assignment, link = seed_indeed_candidate(
        db_session,
        apply_id="apply-1",
        ittk="ittk-1",
        universal="universal-1",
    )
    assert dispositions.build_identifier(db_session, owner_sub="owner-1", candidate_link=link) == {
        "indeedApplyID": "apply-1"
    }

    link.indeed_apply_id = None
    assert dispositions.build_identifier(db_session, owner_sub="owner-1", candidate_link=link) == {
        "ittk": "ittk-1"
    }
    link.ittk = None
    assert dispositions.build_identifier(db_session, owner_sub="owner-1", candidate_link=link) == {
        "universalApplyId": "universal-1"
    }
    link.universal_apply_id = None
    assert dispositions.build_identifier(db_session, owner_sub="owner-1", candidate_link=link) == {
        "alternateIdentifier": {
            "jobIdentifier": {"employerJobId": "employer-job-1"},
            "jobSeekerIdentifier": {"emailAddress": "ana@example.com"},
        }
    }


class DispositionClient:
    def __init__(self, failed=None):
        self.failed = failed or []
        self.calls = []

    def execute(self, query, variables=None):
        assert "SendDispositions" in query
        self.calls.append(variables or {})
        return {
            "partnerDisposition": {
                "send": {
                    "numberGoodDispositions": max(
                        0,
                        len((variables or {}).get("input", {}).get("dispositions", [])) - len(self.failed),
                    ),
                    "failedDispositions": self.failed,
                }
            }
        }


def test_disposition_sync_sends_oldest_first_and_caps_batch_at_25(db_session):
    _job, _candidate, _assignment, link = seed_indeed_candidate(db_session, apply_id="apply-1")
    base = datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)
    for index in range(30):
        db_session.add(
            IndeedDispositionEvent(
                owner_sub="owner-1",
                candidate_link_id=link.id,
                local_status=f"RAW_{index}",
                indeed_status="REVIEW",
                status_changed_at=base + timedelta(minutes=index),
                sync_status="PENDING",
            )
        )
    db_session.commit()
    fake = DispositionClient()

    result = service.sync_dispositions(
        db_session,
        owner_sub="owner-1",
        limit=25,
        client=fake,
        settings=settings(),
    )

    sent = fake.calls[0]["input"]["dispositions"]
    assert len(sent) == 25
    assert [item["rawDispositionStatus"] for item in sent] == [f"RAW_{i}" for i in range(25)]
    assert result == {"selected": 25, "sent": 25, "failed": 0}
    assert db_session.query(IndeedDispositionEvent).filter_by(sync_status="PENDING").count() == 5


def test_disposition_partial_failure_with_null_response_fields_marks_same_application_conservatively(db_session):
    _job, _candidate, _assignment, link = seed_indeed_candidate(db_session, apply_id="apply-1")
    first_time = datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)
    second_time = first_time + timedelta(minutes=5)
    db_session.add_all(
        [
            IndeedDispositionEvent(
                owner_sub="owner-1",
                candidate_link_id=link.id,
                local_status="APPLIED",
                indeed_status="NEW",
                status_changed_at=first_time,
                sync_status="PENDING",
            ),
            IndeedDispositionEvent(
                owner_sub="owner-1",
                candidate_link_id=link.id,
                local_status="INTERVIEW",
                indeed_status="INTERVIEW",
                status_changed_at=second_time,
                sync_status="PENDING",
            ),
        ]
    )
    db_session.commit()
    fake = DispositionClient(
        failed=[
            {
                "identifiedBy": {
                    "indeedApplyID": "apply-1",
                    "ittk": None,
                    "universalApplyId": None,
                    "alternateIdentifier": None,
                },
                "rationale": "sandbox rejection",
            }
        ]
    )

    result = service.sync_dispositions(
        db_session,
        owner_sub="owner-1",
        client=fake,
        settings=settings(),
    )

    assert result == {"selected": 2, "sent": 0, "failed": 2}
    events = db_session.query(IndeedDispositionEvent).order_by(IndeedDispositionEvent.status_changed_at).all()
    assert all(event.sync_status == "FAILED" for event in events)
    assert all(event.last_error == "sandbox rejection" for event in events)


def test_candidate_details_are_owner_scoped_and_expose_resume_without_core_provider_fields(db_session):
    job, candidate, _assignment, link = seed_indeed_candidate(db_session)
    link.resume_name = "ana.pdf"
    link.resume_url = "https://example.invalid/private-resume"
    link.source_name = "Indeed Smart Sourcing"
    db_session.commit()

    details = service.get_candidate_details(
        db_session,
        owner_sub="owner-1",
        job_id=job.id,
        candidate_id=candidate.id,
    )
    assert details["source_name"] == "Indeed Smart Sourcing"
    assert details["resume_name"] == "ana.pdf"
    assert details["resume_url"] == "https://example.invalid/private-resume"
    assert not hasattr(candidate, "indeed_apply_id")
