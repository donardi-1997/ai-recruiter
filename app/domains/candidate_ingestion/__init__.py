"""Provider-neutral candidate ingestion domain."""

from app.domains.candidate_ingestion.models import (
    CandidateIngestionDocument,
    CandidateIngestionEvent,
)

__all__ = ["CandidateIngestionEvent", "CandidateIngestionDocument"]
