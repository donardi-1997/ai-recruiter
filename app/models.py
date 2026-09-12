"""SQLAlchemy ORM models — sync PostgreSQL."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db import Base


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    name = Column(Text, nullable=False)
    email = Column(Text, nullable=True)
    # Cognito subject that owns this candidate.
    # Nullable in ORM for backwards-compatible tests; production
    # migration enforces NOT NULL after legacy backfill.
    owner_sub = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    metadata_ = Column("metadata", JSON, nullable=True, default=dict)

    rankings = relationship("RankingItem", back_populates="candidate", cascade="all, delete-orphan")
    jobs = relationship("JobCandidate", back_populates="candidate", cascade="all, delete-orphan")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    # Cognito subject that owns this job.
    owner_sub = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    rankings = relationship("Ranking", back_populates="job", cascade="all, delete-orphan")
    candidates = relationship("JobCandidate", back_populates="job", cascade="all, delete-orphan")


class JobCandidate(Base):
    __tablename__ = "job_candidates"

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    job_id = Column(
        UUID(as_uuid=False),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_id = Column(
        UUID(as_uuid=False),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    job = relationship("Job", back_populates="candidates")
    candidate = relationship("Candidate", back_populates="jobs")


class Evaluation(Base):
    __tablename__ = "evaluations"

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    candidate_id = Column(
        UUID(as_uuid=False),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id = Column(
        UUID(as_uuid=False),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(Text, nullable=False, default="COMPLETED")
    match_score = Column(Float, nullable=False, default=0.0)
    recommendation = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    strengths = Column(JSON, nullable=True, default=list)
    gaps = Column(JSON, nullable=True, default=list)
    # Full requirement-level analysis:
    # requirement/status/evidence.
    requirements = Column(JSON, nullable=True, default=list)
    error_message = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class Ranking(Base):
    __tablename__ = "rankings"

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    job_id = Column(
        UUID(as_uuid=False),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    ranking_version = Column(Integer, nullable=False, default=0)
    generated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    mode = Column(Text, nullable=False, default="full")
    notes = Column(Text, nullable=True)

    job = relationship("Job", back_populates="rankings")
    items = relationship(
        "RankingItem",
        back_populates="ranking",
        order_by="RankingItem.position",
        cascade="all, delete-orphan",
    )


class RankingItem(Base):
    __tablename__ = "ranking_items"

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    ranking_id = Column(
        UUID(as_uuid=False),
        ForeignKey("rankings.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_id = Column(
        UUID(as_uuid=False),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    score = Column(Float, nullable=False, default=0.0)
    position = Column(Integer, nullable=False)

    ranking = relationship("Ranking", back_populates="items")
    candidate = relationship("Candidate", back_populates="rankings")


class ImportBatch(Base):
    """Durable state for one job-scoped bulk candidate import."""

    __tablename__ = "import_batches"
    __table_args__ = (
        Index("idx_import_batches_owner_created", "owner_sub", "created_at"),
        Index("idx_import_batches_job_created", "job_id", "created_at"),
        Index("idx_import_batches_status_heartbeat", "status", "heartbeat_at"),
    )

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    job_id = Column(
        UUID(as_uuid=False),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_sub = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="UPLOADING")
    current_stage = Column(Text, nullable=False, default="UPLOADING")
    upload_total = Column(Integer, nullable=False, default=0)
    uploaded_items = Column(Integer, nullable=False, default=0)
    total_items = Column(Integer, nullable=False, default=0)
    processed_items = Column(Integer, nullable=False, default=0)
    successful_items = Column(Integer, nullable=False, default=0)
    reused_items = Column(Integer, nullable=False, default=0)
    failed_items = Column(Integer, nullable=False, default=0)
    evaluated_items = Column(Integer, nullable=False, default=0)
    evaluation_failed_items = Column(Integer, nullable=False, default=0)
    ranking_ready = Column(Boolean, nullable=False, default=False)
    ranking_version = Column(Integer, nullable=True)
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
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ImportItem(Base):
    """One top-level upload, archive container, or expanded CV document."""

    __tablename__ = "import_items"
    __table_args__ = (
        Index("idx_import_items_batch_status", "batch_id", "status"),
        Index("idx_import_items_candidate", "candidate_id"),
    )

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    batch_id = Column(
        UUID(as_uuid=False),
        ForeignKey("import_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_item_id = Column(
        UUID(as_uuid=False),
        ForeignKey("import_items.id", ondelete="CASCADE"),
        nullable=True,
    )
    kind = Column(Text, nullable=False)
    original_filename = Column(Text, nullable=False)
    staging_s3_key = Column(Text, nullable=False)
    content_type = Column(Text, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    document_sha256 = Column(Text, nullable=True)
    candidate_id = Column(
        UUID(as_uuid=False),
        ForeignKey("candidates.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(Text, nullable=False, default="UPLOADING")
    current_stage = Column(Text, nullable=False, default="UPLOADING")
    outcome = Column(Text, nullable=True)
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


class CandidateIdentity(Base):
    """Owner-scoped strong identity used for safe automatic deduplication."""

    __tablename__ = "candidate_identities"
    __table_args__ = (
        UniqueConstraint(
            "owner_sub",
            "kind",
            "value",
            name="uq_candidate_identity_owner_kind_value",
        ),
        Index("idx_candidate_identities_candidate", "candidate_id"),
    )

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    owner_sub = Column(Text, nullable=False)
    candidate_id = Column(
        UUID(as_uuid=False),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind = Column(Text, nullable=False)
    value = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
