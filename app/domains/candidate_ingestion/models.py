"""Durable provider-neutral persistence for candidate ingestion."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db import Base


class CandidateIngestionEvent(Base):
    """One externally received candidate-ingestion event."""

    __tablename__ = "candidate_ingestion_events"
    __table_args__ = (
        UniqueConstraint(
            "owner_sub",
            "source",
            "provider",
            "source_account",
            "external_id",
            name="uq_candidate_ingestion_external_event",
        ),
        Index(
            "idx_candidate_ingestion_owner_status",
            "owner_sub",
            "status",
        ),
        Index(
            "idx_candidate_ingestion_dispatch",
            "status",
            "queue_dispatched_at",
        ),
        Index(
            "idx_candidate_ingestion_job_created",
            "job_id",
            "created_at",
        ),
    )

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    owner_sub = Column(Text, nullable=False)
    source = Column(Text, nullable=False)
    provider = Column(Text, nullable=False)
    source_account = Column(Text, nullable=False, default="")
    external_id = Column(Text, nullable=False)
    job_id = Column(
        UUID(as_uuid=False),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    candidate_id = Column(
        UUID(as_uuid=False),
        ForeignKey("candidates.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(Text, nullable=False, default="RECEIVED")
    raw_metadata = Column(JSON, nullable=True, default=dict)
    raw_s3_key = Column(Text, nullable=True)
    bedrock_ingestion_job_id = Column(Text, nullable=True)
    queue_dispatched_at = Column(DateTime(timezone=True), nullable=True)
    processing_token = Column(Text, nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
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

    documents = relationship(
        "CandidateIngestionDocument",
        back_populates="ingestion_event",
        cascade="all, delete-orphan",
    )
    indeed_email_resume_task = relationship(
        "IndeedEmailResumeTask",
        back_populates="ingestion_event",
        uselist=False,
        cascade="all, delete-orphan",
    )


class CandidateIngestionDocument(Base):
    """One source document attached to a candidate ingestion event."""

    __tablename__ = "candidate_ingestion_documents"
    __table_args__ = (
        Index(
            "idx_candidate_ingestion_documents_event_status",
            "ingestion_event_id",
            "status",
        ),
        Index(
            "idx_candidate_ingestion_documents_sha",
            "document_sha256",
        ),
    )

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    ingestion_event_id = Column(
        UUID(as_uuid=False),
        ForeignKey("candidate_ingestion_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename = Column(Text, nullable=False)
    content_type = Column(Text, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    source_s3_key = Column(Text, nullable=False)
    document_sha256 = Column(Text, nullable=True)
    canonical_s3_key = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="STORED")
    error_code = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
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

    ingestion_event = relationship(
        "CandidateIngestionEvent",
        back_populates="documents",
    )


class CandidateIngestionCursor(Base):
    """Durable incremental-sync cursor isolated by tenant, provider and source account."""

    __tablename__ = "candidate_ingestion_cursors"
    __table_args__ = (
        UniqueConstraint(
            "owner_sub",
            "source",
            "provider",
            "source_account",
            name="uq_candidate_ingestion_cursor_source",
        ),
        Index(
            "idx_candidate_ingestion_cursor_owner",
            "owner_sub",
            "source",
            "provider",
        ),
    )

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    owner_sub = Column(Text, nullable=False)
    source = Column(Text, nullable=False)
    provider = Column(Text, nullable=False)
    source_account = Column(Text, nullable=False)
    cursor_value = Column(Text, nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
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


class IndeedEmailResumeTask(Base):
    """Durable browser-download task for one Indeed application email."""

    __tablename__ = "indeed_email_resume_tasks"
    __table_args__ = (
        UniqueConstraint(
            "ingestion_event_id",
            name="uq_indeed_email_resume_task_event",
        ),
        Index(
            "idx_indeed_email_resume_task_claim",
            "status",
            "available_at",
            "created_at",
        ),
        Index(
            "idx_indeed_email_resume_task_owner_status",
            "owner_sub",
            "status",
        ),
    )

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    owner_sub = Column(Text, nullable=False)
    ingestion_event_id = Column(
        UUID(as_uuid=False),
        ForeignKey("candidate_ingestion_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id = Column(
        UUID(as_uuid=False),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    candidate_name = Column(Text, nullable=False)
    job_title = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="WAITING_DOWNLOAD")
    lease_token = Column(Text, nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    available_at = Column(DateTime(timezone=True), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    last_error_code = Column(Text, nullable=True)
    last_error_message = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
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

    ingestion_event = relationship(
        "CandidateIngestionEvent",
        back_populates="indeed_email_resume_task",
    )
