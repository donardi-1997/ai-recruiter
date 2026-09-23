from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db import Base
from app.deps import get_db
from app.domains.candidate_ingestion import indeed_agent_sync
from app.domains.candidate_ingestion.indeed_agent_auth import (
    AgentPrincipal,
    get_indeed_resume_agent_principal,
)
from app.main import app


@pytest.fixture()
def api():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_indeed_resume_agent_principal] = (
        lambda: AgentPrincipal(owner_sub="owner-a")
    )
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_sync_route_preserves_safe_stage_code(api, monkeypatch):
    def fail_sync(db, *, owner_sub):
        raise indeed_agent_sync.ResumeSyncStageError("GMAIL_TOKEN_REFRESH_REJECTED")

    monkeypatch.setattr(indeed_agent_sync, "sync_one_page", fail_sync)

    response = api.post("/api/agents/indeed-resume/sync")

    assert response.status_code == 502
    assert response.json() == {"detail": "GMAIL_TOKEN_REFRESH_REJECTED"}
