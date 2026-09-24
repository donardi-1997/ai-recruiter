"""Candidate retention and veto contracts."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.candidates import repository
from app.main import app
from app.models import Candidate, Job


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_operational_candidate_delete_routes_are_not_exposed():
    candidate_routes = [
        route
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/candidates")
    ]

    assert not any(
        "DELETE" in getattr(route, "methods", set())
        and getattr(route, "path", "") in {
            "/api/candidates",
            "/api/candidates/{candidate_id}",
        }
        for route in candidate_routes
    )


def test_candidate_ban_and_unban_preserve_audit_history():
    engine, db = _db()
    try:
        candidate = Candidate(
            name="Persona retenida",
            owner_sub="owner-1",
            metadata_={},
        )
        db.add(candidate)
        db.commit()
        db.refresh(candidate)

        candidate, first_event, changed = repository.set_candidate_restriction(
            db,
            candidate,
            is_banned=True,
            reason="Fraude documental verificado",
            created_by_sub="admin-sub",
        )

        assert changed is True
        assert candidate.is_banned is True
        assert candidate.banned_reason == "Fraude documental verificado"
        assert candidate.banned_by_sub == "admin-sub"
        assert candidate.banned_at is not None
        assert first_event.action == "BANNED"

        candidate, second_event, changed = repository.set_candidate_restriction(
            db,
            candidate,
            is_banned=False,
            reason="Veto levantado después de revisión",
            created_by_sub="director-sub",
        )

        assert changed is True
        assert candidate.is_banned is False
        assert candidate.banned_reason is None
        assert candidate.banned_by_sub is None
        assert candidate.banned_at is None
        assert second_event.action == "UNBANNED"

        history = repository.list_candidate_restriction_events(
            db,
            candidate_id=candidate.id,
        )
        assert [event.action for event in history] == ["UNBANNED", "BANNED"]
        assert [event.created_by_sub for event in history] == [
            "director-sub",
            "admin-sub",
        ]
    finally:
        db.close()
        engine.dispose()


def test_banned_candidate_is_skipped_when_assigning_to_job():
    engine, db = _db()
    try:
        job = Job(
            title="Vacante",
            owner_sub="owner-1",
        )
        banned = Candidate(
            name="Vetado",
            owner_sub="owner-1",
            metadata_={},
            is_banned=True,
            banned_reason="No elegible",
        )
        available = Candidate(
            name="Disponible",
            owner_sub="owner-1",
            metadata_={},
        )
        db.add_all([job, banned, available])
        db.commit()

        assigned, skipped = repository.assign_candidates_to_job(
            db,
            job.id,
            [banned.id, available.id],
            owner_sub="owner-1",
        )

        assert assigned == 1
        assert skipped == 1
        assert repository.get_job_candidate(
            db,
            job_id=job.id,
            candidate_id=banned.id,
            owner_sub="owner-1",
        ) is None
        assert repository.get_job_candidate(
            db,
            job_id=job.id,
            candidate_id=available.id,
            owner_sub="owner-1",
        ) is not None
    finally:
        db.close()
        engine.dispose()
