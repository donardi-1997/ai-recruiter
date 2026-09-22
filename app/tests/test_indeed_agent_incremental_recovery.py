from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.candidate_ingestion import indeed_agent_sync
from app.domains.candidate_ingestion.models import (
    CandidateIngestionEvent,
    IndeedEmailResumeTask,
)
from app.models import IndeedJobLink, Job


def test_incremental_sync_recovers_application_after_vacancy_refresh(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        job = Job(
            title="Cloud Engineer",
            description="Indeed description",
            indeed_description="Indeed description",
            active_description_source="indeed",
            owner_sub="owner-1",
            evaluation_profile={},
        )
        db.add(job)
        db.flush()
        db.add(
            IndeedJobLink(
                job_id=job.id,
                owner_sub="owner-1",
                discovery_key="employer-ui:abc-123",
                external_status={"origin": "EMPLOYER_UI"},
            )
        )
        event = CandidateIngestionEvent(
            owner_sub="owner-1",
            source="EMAIL",
            provider="INDEED",
            source_account="katherine@example.com",
            external_id="gmail-waiting-1",
            status="NEEDS_REVIEW",
            raw_metadata={
                "candidate_name": "Ada Candidate",
                "job_title": "Cloud Engineer",
                "external_job_id": "abc-123",
                "gmail_message_id": "gmail-waiting-1",
            },
            last_error_code="INDEED_JOB_NOT_SYNCED_YET",
        )
        db.add(event)
        db.commit()

        monkeypatch.setattr(
            indeed_agent_sync.gmail_integration,
            "sync_mailbox",
            lambda *args, **kwargs: {
                "mode": "INCREMENTAL",
                "discovered": 0,
                "created": 0,
                "existing": 0,
                "needs_review": 0,
                "skipped": 0,
                "cursor_value": "800",
            },
        )

        result = indeed_agent_sync.sync_one_page(
            db,
            owner_sub="owner-1",
            mailbox_client=object(),
        )

        db.refresh(event)
        task = db.query(IndeedEmailResumeTask).one()
        assert result["applications_recovered"] == 1
        assert result["discovered"] == 0
        assert event.status == "RECEIVED"
        assert task.job_id == job.id
        assert task.status == "WAITING_DOWNLOAD"
    finally:
        db.close()
        engine.dispose()
