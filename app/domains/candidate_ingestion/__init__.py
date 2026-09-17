"""Provider-neutral candidate ingestion domain."""

from app.domains.candidate_ingestion.models import (
    CandidateIngestionDocument,
    CandidateIngestionEvent,
    IndeedEmailResumeTask,
)

__all__ = [
    "CandidateIngestionEvent",
    "CandidateIngestionDocument",
    "IndeedEmailResumeTask",
]
