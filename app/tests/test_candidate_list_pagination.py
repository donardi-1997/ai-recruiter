"""Pagination contract for the owner-scoped candidates list."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.candidates import router as candidates_router
from app.models import Candidate


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_candidates_endpoint_returns_fixed_page_of_20_with_metadata():
    engine, db = _db()
    try:
        db.add_all(
            [
                Candidate(name=f"Candidate {index:02d}", owner_sub="owner-1", metadata_={})
                for index in range(1, 26)
            ]
            + [
                Candidate(name=f"Other {index:02d}", owner_sub="owner-2", metadata_={})
                for index in range(1, 4)
            ]
        )
        db.commit()

        payload = candidates_router.list_candidates(
            page=2,
            page_size=20,
            db=db,
            _user={"sub": "owner-1"},
        )

        assert payload["total"] == 25
        assert payload["page"] == 2
        assert payload["page_size"] == 20
        assert payload["pages"] == 2
        assert len(payload["items"]) == 5
    finally:
        db.close()
        engine.dispose()
