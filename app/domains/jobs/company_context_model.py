"""Persistence model for versioned tenant company context."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Integer, JSON, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class CompanyContext(Base):
    """Versioned organization context used only for vacancy enrichment."""

    __tablename__ = "company_contexts"
    __table_args__ = (
        UniqueConstraint(
            "owner_sub",
            "version",
            name="uq_company_context_owner_version",
        ),
        Index("idx_company_context_owner_status", "owner_sub", "status"),
    )

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    owner_sub = Column(Text, nullable=False)
    organization_name = Column(Text, nullable=False)
    version = Column(Integer, nullable=False)
    status = Column(Text, nullable=False, default="ACTIVE")
    context = Column(JSON, nullable=False, default=dict)
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
