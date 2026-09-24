"""SQLAlchemy ORM models — sync PostgreSQL."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
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
    is_banned = Column(Boolean, nullable=False, default=False)
    banned_at = Column(DateTime(timezone=True), nullable=True)
    banned_by_sub = Column(Text, nullable=True)
    banned_reason = Column(Text, nullable=True)

    rankings = relationship("RankingItem", back_populates="candidate", cascade="all, delete-orphan")
    jobs = relationship("JobCandidate", back_populates="candidate", cascade="all, delete-orphan")
    indeed_links = relationship("IndeedCandidateLink", back_populates="candidate", cascade="all, delete-orphan")
    restriction_events = relationship(
        "CandidateRestrictionEvent",
        back_populates="candidate",
        passive_deletes=True,
        order_by="CandidateRestrictionEvent.created_at",
    )


class CandidateRestrictionEvent(Base):
    """Auditable ban/unban event for a retained candidate."""

    __tablename__ = "candidate_restriction_events"
    __table_args__ = (
        Index(
            "idx_candidate_restriction_events_candidate_created",
            "candidate_id",
            "created_at",
        ),
    )

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    candidate_id = Column(
        UUID(as_uuid=False),
        ForeignKey("candidates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    action = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    created_by_sub = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    candidate = relationship("Candidate", back_populates="restriction_events")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    indeed_description = Column(Text, nullable=True)
    ai_description = Column(Text, nullable=True)
    active_description_source = Column(Text, nullable=False, default="indeed")
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
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "candidate_id",
            name="uq_job_candidates_job_candidate",
        ),
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
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "candidate_id",
            name="uq_evaluations_job_candidate",
        ),
    )

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
    staged_at = Column(DateTime(timezone=True), nullable=True)
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


class UserProfile(Base):
    """Internal employee profile linked to one Cognito identity."""

    __tablename__ = "user_profiles"
    __table_args__ = (
        UniqueConstraint("cognito_sub", name="uq_user_profiles_cognito_sub"),
        UniqueConstraint("email", name="uq_user_profiles_email"),
        Index("idx_user_profiles_status", "status"),
    )

    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    cognito_sub = Column(Text, nullable=False)
    email = Column(Text, nullable=False)
    first_name = Column(Text, nullable=True)
    last_name = Column(Text, nullable=True)
    job_title = Column(Text, nullable=True)
    department = Column(Text, nullable=True)
    hire_date = Column(Date, nullable=True)
    onboarding_status = Column(Text, nullable=False, default="PENDING")
    onboarding_started_at = Column(DateTime(timezone=True), nullable=True)
    onboarding_completed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Text, nullable=False, default="ACTIVE")
    created_by_sub = Column(Text, nullable=True)
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

    role_assignments = relationship(
        "UserRole",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    score_events = relationship(
        "EmployeeScoreEvent",
        back_populates="employee",
        foreign_keys="EmployeeScoreEvent.employee_id",
        passive_deletes=True,
    )


class Role(Base):
    """Named RBAC role used to group permissions."""

    __tablename__ = "roles"

    code = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)

    user_assignments = relationship(
        "UserRole",
        back_populates="role",
        cascade="all, delete-orphan",
    )
    permission_assignments = relationship(
        "RolePermission",
        back_populates="role",
        cascade="all, delete-orphan",
    )


class Permission(Base):
    """Granular capability enforced by backend authorization dependencies."""

    __tablename__ = "permissions"

    code = Column(Text, primary_key=True)
    description = Column(Text, nullable=True)

    role_assignments = relationship(
        "RolePermission",
        back_populates="permission",
        cascade="all, delete-orphan",
    )


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_code", name="uq_user_roles_user_role"),
        Index("idx_user_roles_role_code", "role_code"),
    )

    user_id = Column(
        Text,
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_code = Column(
        Text,
        ForeignKey("roles.code", ondelete="CASCADE"),
        primary_key=True,
    )
    assigned_by_sub = Column(Text, nullable=True)
    assigned_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    user = relationship("UserProfile", back_populates="role_assignments")
    role = relationship("Role", back_populates="user_assignments")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint(
            "role_code",
            "permission_code",
            name="uq_role_permissions_role_permission",
        ),
        Index("idx_role_permissions_permission_code", "permission_code"),
    )

    role_code = Column(
        Text,
        ForeignKey("roles.code", ondelete="CASCADE"),
        primary_key=True,
    )
    permission_code = Column(
        Text,
        ForeignKey("permissions.code", ondelete="CASCADE"),
        primary_key=True,
    )

    role = relationship("Role", back_populates="permission_assignments")
    permission = relationship("Permission", back_populates="role_assignments")


class EmployeeScoreEvent(Base):
    """Append-only employee score movement visible only to Direction."""

    __tablename__ = "employee_score_events"
    __table_args__ = (
        CheckConstraint("points <> 0", name="ck_employee_score_events_nonzero_points"),
        Index(
            "idx_employee_score_events_employee_status_date",
            "employee_id",
            "status",
            "event_date",
        ),
    )

    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    employee_id = Column(
        Text,
        ForeignKey("user_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    points = Column(Integer, nullable=False)
    description = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="ACTIVE")
    event_date = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    created_by_sub = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    voided_at = Column(DateTime(timezone=True), nullable=True)
    voided_by_sub = Column(Text, nullable=True)
    void_reason = Column(Text, nullable=True)

    employee = relationship(
        "UserProfile",
        back_populates="score_events",
        foreign_keys=[employee_id],
    )


class TrainingCourse(Base):
    """Internal learning course."""

    __tablename__ = "training_courses"
    __table_args__ = (
        Index("idx_training_courses_status", "status"),
    )

    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    is_onboarding = Column(Boolean, nullable=False, default=False)
    status = Column(Text, nullable=False, default="DRAFT")
    created_by_sub = Column(Text, nullable=False)
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

    modules = relationship(
        "TrainingModule",
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="TrainingModule.position",
    )
    assignments = relationship(
        "TrainingAssignment",
        back_populates="course",
        cascade="all, delete-orphan",
    )
    quiz = relationship(
        "TrainingQuiz",
        back_populates="course",
        cascade="all, delete-orphan",
        uselist=False,
    )


class TrainingModule(Base):
    __tablename__ = "training_modules"
    __table_args__ = (
        UniqueConstraint(
            "course_id",
            "position",
            name="uq_training_modules_course_position",
        ),
    )

    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    course_id = Column(
        Text,
        ForeignKey("training_courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    audience_job_title = Column(Text, nullable=True)
    audience_department = Column(Text, nullable=True)
    position = Column(Integer, nullable=False, default=1)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    course = relationship("TrainingCourse", back_populates="modules")
    lessons = relationship(
        "TrainingLesson",
        back_populates="module",
        cascade="all, delete-orphan",
        order_by="TrainingLesson.position",
    )


class TrainingLesson(Base):
    __tablename__ = "training_lessons"
    __table_args__ = (
        UniqueConstraint(
            "module_id",
            "position",
            name="uq_training_lessons_module_position",
        ),
    )

    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    module_id = Column(
        Text,
        ForeignKey("training_modules.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    video_url = Column(Text, nullable=True)
    video_storage_key = Column(Text, nullable=True)
    video_content_type = Column(Text, nullable=True)
    video_size_bytes = Column(Integer, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    content_type = Column(Text, nullable=False, default="VIDEO")
    external_url = Column(Text, nullable=True)
    estimated_minutes = Column(Integer, nullable=True)
    checklist_items = Column(JSON, nullable=True, default=list)
    is_optional = Column(Boolean, nullable=False, default=False)
    position = Column(Integer, nullable=False, default=1)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    module = relationship("TrainingModule", back_populates="lessons")
    progress_entries = relationship(
        "TrainingLessonProgress",
        back_populates="lesson",
        cascade="all, delete-orphan",
    )


class TrainingAssignment(Base):
    __tablename__ = "training_assignments"
    __table_args__ = (
        UniqueConstraint(
            "course_id",
            "employee_id",
            name="uq_training_assignments_course_employee",
        ),
        Index(
            "idx_training_assignments_employee_status",
            "employee_id",
            "status",
        ),
    )

    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    course_id = Column(
        Text,
        ForeignKey("training_courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id = Column(
        Text,
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(Text, nullable=False, default="ASSIGNED")
    assigned_by_sub = Column(Text, nullable=False)
    assigned_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    course = relationship("TrainingCourse", back_populates="assignments")
    employee = relationship("UserProfile")
    lesson_progress = relationship(
        "TrainingLessonProgress",
        back_populates="assignment",
        cascade="all, delete-orphan",
    )
    quiz_attempts = relationship(
        "TrainingQuizAttempt",
        back_populates="assignment",
        cascade="all, delete-orphan",
    )


class TrainingLessonProgress(Base):
    __tablename__ = "training_lesson_progress"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id",
            "lesson_id",
            name="uq_training_lesson_progress_assignment_lesson",
        ),
        Index(
            "idx_training_lesson_progress_assignment_status",
            "assignment_id",
            "status",
        ),
    )

    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    assignment_id = Column(
        Text,
        ForeignKey("training_assignments.id", ondelete="CASCADE"),
        nullable=False,
    )
    lesson_id = Column(
        Text,
        ForeignKey("training_lessons.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(Text, nullable=False, default="COMPLETED")
    details = Column(JSON, nullable=True, default=dict)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    assignment = relationship(
        "TrainingAssignment",
        back_populates="lesson_progress",
    )
    lesson = relationship(
        "TrainingLesson",
        back_populates="progress_entries",
    )


class TrainingQuiz(Base):
    __tablename__ = "training_quizzes"
    __table_args__ = (
        UniqueConstraint("course_id", name="uq_training_quizzes_course"),
    )

    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    course_id = Column(
        Text,
        ForeignKey("training_courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(Text, nullable=False)
    passing_score = Column(Integer, nullable=False, default=70)
    created_by_sub = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    course = relationship("TrainingCourse", back_populates="quiz")
    questions = relationship(
        "TrainingQuizQuestion",
        back_populates="quiz",
        cascade="all, delete-orphan",
        order_by="TrainingQuizQuestion.position",
    )
    attempts = relationship(
        "TrainingQuizAttempt",
        back_populates="quiz",
        cascade="all, delete-orphan",
    )


class TrainingQuizQuestion(Base):
    __tablename__ = "training_quiz_questions"
    __table_args__ = (
        UniqueConstraint(
            "quiz_id",
            "position",
            name="uq_training_quiz_questions_quiz_position",
        ),
    )

    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    quiz_id = Column(
        Text,
        ForeignKey("training_quizzes.id", ondelete="CASCADE"),
        nullable=False,
    )
    prompt = Column(Text, nullable=False)
    options = Column(JSON, nullable=False, default=list)
    correct_option = Column(Integer, nullable=False)
    position = Column(Integer, nullable=False, default=1)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    quiz = relationship("TrainingQuiz", back_populates="questions")


class TrainingQuizAttempt(Base):
    __tablename__ = "training_quiz_attempts"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id",
            "attempt_number",
            name="uq_training_quiz_attempts_assignment_number",
        ),
        Index(
            "idx_training_quiz_attempts_assignment_submitted",
            "assignment_id",
            "submitted_at",
        ),
    )

    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    assignment_id = Column(
        Text,
        ForeignKey("training_assignments.id", ondelete="CASCADE"),
        nullable=False,
    )
    quiz_id = Column(
        Text,
        ForeignKey("training_quizzes.id", ondelete="CASCADE"),
        nullable=False,
    )
    answers = Column(JSON, nullable=False, default=dict)
    score_percent = Column(Integer, nullable=False)
    passed = Column(Boolean, nullable=False, default=False)
    attempt_number = Column(Integer, nullable=False)
    submitted_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    assignment = relationship(
        "TrainingAssignment",
        back_populates="quiz_attempts",
    )
    quiz = relationship("TrainingQuiz", back_populates="attempts")

