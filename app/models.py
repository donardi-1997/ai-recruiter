"""SQLAlchemy ORM models — sync PostgreSQL.

Table names use REEMPLAZAR_DB_TABLE_* placeholders.
Schema matches migration 001_create_tables.py (UUID PKs).
"""

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


# ============================================================
# CANDIDATES
# ============================================================

class Candidate(Base):
    __tablename__ = "REEMPLAZAR_DB_TABLE_CANDIDATES"

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


# ============================================================
# JOBS
# ============================================================

class Job(Base):
    __tablename__ = "REEMPLAZAR_DB_TABLE_JOBS"

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    title = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    rankings = relationship("Ranking", back_populates="job")


# ============================================================
# RANKINGS
# ============================================================

class Ranking(Base):
    __tablename__ = "REEMPLAZAR_DB_TABLE_RANKINGS"

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    job_id = Column(
        UUID(as_uuid=False),
        ForeignKey("REEMPLAZAR_DB_TABLE_JOBS.id", ondelete="CASCADE"),
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


# ============================================================
# RANKING ITEMS
# ============================================================

class RankingItem(Base):
    __tablename__ = "REEMPLAZAR_DB_TABLE_RANKING_ITEMS"

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    ranking_id = Column(
        UUID(as_uuid=False),
        ForeignKey("REEMPLAZAR_DB_TABLE_RANKINGS.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_id = Column(
        UUID(as_uuid=False),
        ForeignKey("REEMPLAZAR_DB_TABLE_CANDIDATES.id", ondelete="CASCADE"),
        nullable=False,
    )
    score = Column(Float, nullable=False, default=0.0)
    position = Column(Integer, nullable=False)

    ranking = relationship("Ranking", back_populates="items")
    candidate = relationship("Candidate", back_populates="rankings")
