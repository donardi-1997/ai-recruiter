"""SQLAlchemy ORM models — sync PostgreSQL."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
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
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    metadata_ = Column("metadata", JSON, nullable=True, default=dict)

    rankings = relationship("RankingItem", back_populates="candidate")
    jobs = relationship("JobCandidate", back_populates="candidate")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    rankings = relationship("Ranking", back_populates="job")
    candidates = relationship("JobCandidate", back_populates="job")


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
    match_score = Column(Float, nullable=False, default=0.0)
    recommendation = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    strengths = Column(JSON, nullable=True, default=list)
    gaps = Column(JSON, nullable=True, default=list)
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
