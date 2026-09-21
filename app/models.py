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
    owner_sub = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    metadata_ = Column("metadata", JSON, nullable=True, default=dict)

    rankings = relationship("RankingItem", back_populates="candidate", cascade="all, delete-orphan")
    jobs = relationship("JobCandidate", back_populates="candidate", cascade="all, delete-orphan")
    indeed_links = relationship("IndeedCandidateLink", back_populates="candidate", cascade="all, delete-orphan")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    owner_sub = Column(Text, nullable=True)
    country_code = Column(Text, nullable=True)
    city = Column(Text, nullable=True)
    employment_type = Column(Text, nullable=True)
    public_slug = Column(Text, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    evaluation_version = Column(Integer, nullable=False, default=1)
    evaluation_profile = Column(JSON, nullable=False, default=dict)
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

    rankings = relationship("Ranking", back_populates="job", cascade="all, delete-orphan")
    candidates = relationship("JobCandidate", back_populates="job", cascade="all, delete-orphan")
    indeed_link = relationship("IndeedJobLink", back_populates="job", uselist=False, cascade="all, delete-orphan")
    indeed_events = relationship("IndeedSyncEvent", back_populates="job")
    indeed_candidate_links = relationship("IndeedCandidateLink", back_populates="job", cascade="all, delete-orphan")


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
    application_status = Column(Text, nullable=False, default="APPLIED")
    status_changed_at = Column(
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
    job_evaluation_version = Column(Integer, nullable=False, default=1)
    status = Column(Text, nullable=False, default="COMPLETED")
    match_score = Column(Float, nullable=False, default=0.0)
    recommendation = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    strengths = Column(JSON, nullable=True, default=list)
    gaps = Column(JSON, nullable=True, default=list)
    requirements = Column(JSON, nullable=True, default=list)
    error_message = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class JobReevaluationTask(Base):
    """Durable asynchronous reevaluation request for one job version."""

    __tablename__ = "job_reevaluation_tasks"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "target_evaluation_version",
            name="uq_job_reevaluation_job_version",
        ),
        Index("idx_job_reevaluation_owner_created", "owner_sub", "created_at"),
        Index("idx_job_reevaluation_status_heartbeat", "status", "heartbeat_at"),
    )

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    owner_sub = Column(Text, nullable=False)
    job_id = Column(
        UUID(as_uuid=False),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_evaluation_version = Column(Integer, nullable=False)
    status = Column(Text, nullable=False, default="PENDING")
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
    completed_at = Column(DateTime(timezone=True), nullable=True)


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


class IndeedConnection(Base):
    __tablename__ = "indeed_connections"
    __table_args__ = (UniqueConstraint("owner_sub", name="uq_indeed_connections_owner"),)

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_sub = Column(Text, nullable=False)
    employer_id = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="DISCONNECTED")
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class IndeedJobLink(Base):
    __tablename__ = "indeed_job_links"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_indeed_job_links_job"),
        UniqueConstraint(
            "owner_sub",
            "discovery_key",
            name="uq_indeed_job_links_owner_discovery_key",
        ),
        Index("idx_indeed_job_links_owner", "owner_sub"),
    )

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(UUID(as_uuid=False), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    owner_sub = Column(Text, nullable=False)
    discovery_key = Column(Text, nullable=True)
    sourced_posting_id = Column(Text, nullable=True)
    employer_job_id = Column(Text, nullable=True)
    external_status = Column(JSON, nullable=True, default=dict)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    job = relationship("Job", back_populates="indeed_link")


class IndeedSyncEvent(Base):
    __tablename__ = "indeed_sync_events"
    __table_args__ = (
        Index("idx_indeed_sync_events_owner_created", "owner_sub", "created_at"),
        Index("idx_indeed_sync_events_job_created", "job_id", "created_at"),
    )

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_sub = Column(Text, nullable=False)
    job_id = Column(UUID(as_uuid=False), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    operation = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="PENDING")
    external_id = Column(Text, nullable=True)
    error_code = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    job = relationship("Job", back_populates="indeed_events")


class IndeedCandidateLink(Base):
    __tablename__ = "indeed_candidate_links"
    __table_args__ = (
        UniqueConstraint("owner_sub", "asset_id", name="uq_indeed_candidate_links_owner_asset"),
        Index("idx_indeed_candidate_links_owner_job", "owner_sub", "job_id"),
        Index("idx_indeed_candidate_links_candidate", "candidate_id"),
    )

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_sub = Column(Text, nullable=False)
    candidate_id = Column(UUID(as_uuid=False), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(UUID(as_uuid=False), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    asset_id = Column(Text, nullable=False)
    registration_id = Column(Text, nullable=True)
    employer_identifier = Column(Text, nullable=True)
    source_enum_key = Column(Text, nullable=True)
    source_name = Column(Text, nullable=True)
    sourced_posting_id = Column(Text, nullable=True)
    indeed_apply_id = Column(Text, nullable=True)
    ittk = Column(Text, nullable=True)
    universal_apply_id = Column(Text, nullable=True)
    resume_name = Column(Text, nullable=True)
    resume_url = Column(Text, nullable=True)
    staged_test = Column(Boolean, nullable=False, default=False)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    candidate = relationship("Candidate", back_populates="indeed_links")
    job = relationship("Job", back_populates="indeed_candidate_links")
    disposition_events = relationship(
        "IndeedDispositionEvent",
        back_populates="candidate_link",
        cascade="all, delete-orphan",
    )


class IndeedCandidateSyncState(Base):
    __tablename__ = "indeed_candidate_sync_state"
    __table_args__ = (UniqueConstraint("owner_sub", name="uq_indeed_candidate_sync_state_owner"),)

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_sub = Column(Text, nullable=False)
    ack_token = Column(Text, nullable=True)
    last_fetch_at = Column(DateTime(timezone=True), nullable=True)
    last_ack_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class IndeedDispositionEvent(Base):
    __tablename__ = "indeed_disposition_events"
    __table_args__ = (
        UniqueConstraint(
            "candidate_link_id",
            "local_status",
            "status_changed_at",
            name="uq_indeed_disposition_event_state_time",
        ),
        Index(
            "idx_indeed_disposition_events_owner_status_time",
            "owner_sub",
            "sync_status",
            "status_changed_at",
        ),
    )

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_sub = Column(Text, nullable=False)
    candidate_link_id = Column(
        UUID(as_uuid=False),
        ForeignKey("indeed_candidate_links.id", ondelete="CASCADE"),
        nullable=False,
    )
    local_status = Column(Text, nullable=False)
    indeed_status = Column(Text, nullable=False)
    status_changed_at = Column(DateTime(timezone=True), nullable=False)
    sync_status = Column(Text, nullable=False, default="PENDING")
    attempt_count = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    candidate_link = relationship("IndeedCandidateLink", back_populates="disposition_events")
