"""SQLAlchemy ORM models — sync PostgreSQL.

Table names use REEMPLAZAR_DB_TABLE_* placeholders so they can be
swapped for the actual names when the migration is applied.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import JSON
from sqlalchemy.orm import relationship

from pg_backend.database import Base


# ============================================================
# ENUMS
# ============================================================

RECOMMENDATION_ENUM = (
    "STRONG_MATCH",
    "GOOD_MATCH",
    "PARTIAL_MATCH",
    "LOW_MATCH",
    "PENDING",
)


# ============================================================
# CANDIDATES
# ============================================================

class Candidate(Base):
    __tablename__ = "REEMPLAZAR_DB_TABLE_CANDIDATES"

    candidate_id   = Column(String(36), primary_key=True)
    owner_id       = Column(String(64), nullable=False, index=True)
    name           = Column(Text,       nullable=False)
    filename       = Column(Text,       nullable=False)
    s3_location    = Column(Text,       nullable=False)
    metadata_location = Column(Text)
    ingestion_job_id  = Column(Text)
    ingestion_status  = Column(Text)
    indexed        = Column(Boolean,    nullable=False, default=False)
    created_at     = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at     = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    evaluations = relationship(
        "Evaluation",
        back_populates="candidate",
        lazy="dynamic",
    )
    job_links = relationship(
        "JobCandidate",
        back_populates="candidate",
        lazy="dynamic",
    )


# ============================================================
# JOBS
# ============================================================

class Job(Base):
    __tablename__ = "REEMPLAZAR_DB_TABLE_JOBS"

    job_id       = Column(String(36), primary_key=True)
    owner_id     = Column(String(64), nullable=False, index=True)
    title        = Column(Text,       nullable=False)
    description  = Column(Text,       nullable=False)
    created_at   = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at   = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    evaluations  = relationship(
        "Evaluation",
        back_populates="job",
        lazy="dynamic",
    )
    job_links    = relationship(
        "JobCandidate",
        back_populates="job",
        lazy="dynamic",
    )
    ranking      = relationship(
        "Ranking",
        back_populates="job",
        uselist=False,
        lazy="select",
    )


# ============================================================
# JOB ↔ CANDIDATE  (pivote / asignaciones)
# ============================================================

class JobCandidate(Base):
    __tablename__ = "REEMPLAZAR_DB_TABLE_JOB_CANDIDATES"

    job_id       = Column(
        String(36),
        ForeignKey(
            "REEMPLAZAR_DB_TABLE_JOBS.job_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    candidate_id = Column(
        String(36),
        ForeignKey(
            "REEMPLAZAR_DB_TABLE_CANDIDATES.candidate_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    owner_id     = Column(String(64), nullable=False, index=True)
    status       = Column(
        String(30),
        nullable=False,
        default="PENDING_EVALUATION",
    )
    assigned_at  = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    job       = relationship("Job",       back_populates="job_links")
    candidate = relationship("Candidate", back_populates="job_links")


# ============================================================
# EVALUATIONS
# ============================================================

class Evaluation(Base):
    __tablename__ = "REEMPLAZAR_DB_TABLE_EVALUATIONS"

    job_id          = Column(
        String(36),
        ForeignKey(
            "REEMPLAZAR_DB_TABLE_JOBS.job_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    candidate_id    = Column(
        String(36),
        ForeignKey(
            "REEMPLAZAR_DB_TABLE_CANDIDATES.candidate_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    owner_id        = Column(String(64), nullable=False, index=True)
    job_title       = Column(Text, nullable=False, default="")
    job_description = Column(Text, nullable=False, default="")
    candidate_name  = Column(Text, nullable=False, default="")
    status          = Column(String(20), nullable=False, default="PENDING")
    evaluated_at    = Column(DateTime(timezone=True))
    match_score     = Column(Integer,   nullable=False, default=0)
    recommendation  = Column(
        String(20),
        nullable=False,
        default="LOW_MATCH",
    )
    requirements    = Column(JSON, nullable=False, default=list)
    strengths       = Column(JSON, nullable=False, default=list)
    gaps            = Column(JSON, nullable=False, default=list)
    summary         = Column(Text,  nullable=False, default="")

    job       = relationship("Job",       back_populates="evaluations")
    candidate = relationship("Candidate", back_populates="evaluations")

    __table_args__ = (
        UniqueConstraint("job_id", "candidate_id", name="uq_eval_job_candidate"),
    )


# ============================================================
# RANKINGS
# ============================================================

class Ranking(Base):
    __tablename__ = "REEMPLAZAR_DB_TABLE_RANKINGS"

    job_id = Column(
        String(36),
        ForeignKey(
            "REEMPLAZAR_DB_TABLE_JOBS.job_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    ranking_generated_at = Column(DateTime(timezone=True))
    ranking_version      = Column(Integer, nullable=False, default=0)

    job = relationship("Job", back_populates="ranking")


# ============================================================
# RANKING ITEMS (snapshots opcionales de cada ranking run)
# ============================================================

class RankingItem(Base):
    __tablename__ = "REEMPLAZAR_DB_TABLE_RANKING_ITEMS"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    job_id          = Column(
        String(36),
        ForeignKey(
            "REEMPLAZAR_DB_TABLE_JOBS.job_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    candidate_id    = Column(String(36), nullable=False)
    candidate_name  = Column(Text,      nullable=False, default="")
    match_score     = Column(Integer,   nullable=False, default=0)
    recommendation  = Column(String(20), nullable=False, default="LOW_MATCH")
    rank_position   = Column(Integer,   nullable=False)
    strengths       = Column(JSON,     nullable=False, default=list)
    gaps            = Column(JSON,     nullable=False, default=list)
    ranking_version = Column(Integer,   nullable=False)
    created_at      = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "ranking_version",
            "candidate_id",
            name="uq_ranking_item_per_version",
        ),
    )
