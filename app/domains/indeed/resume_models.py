"""Provider-specific persistence model for durable Indeed resume processing."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db import Base


class IndeedResumeIngestion(Base):
    """Durable asynchronous processing state for one Indeed candidate resume."""

    __tablename__ = "indeed_resume_ingestions"
    __table_args__ = (
        UniqueConstraint(
            "candidate_link_id",
            name="uq_indeed_resume_ingestions_candidate_link",
        ),
        Index(
            "idx_indeed_resume_ingestions_owner_status",
            "owner_sub",
            "status",
        ),
        Index(
            "idx_indeed_resume_ingestions_dispatch",
            "status",
            "queue_dispatched_at",
        ),
    )

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    owner_sub = Column(Text, nullable=False)
    candidate_link_id = Column(
        UUID(as_uuid=False),
        ForeignKey("indeed_candidate_links.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(Text, nullable=False, default="PENDING")
    resume_sha256 = Column(Text, nullable=True)
    canonical_s3_key = Column(Text, nullable=True)
    bedrock_ingestion_job_id = Column(Text, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    queue_dispatched_at = Column(DateTime(timezone=True), nullable=True)
    processing_token = Column(Text, nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    last_error_code = Column(Text, nullable=True)
    last_error_message = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    candidate_link = relationship("IndeedCandidateLink")
