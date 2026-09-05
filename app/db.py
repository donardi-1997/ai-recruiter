"""Database engine, session factory, and base model."""

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/ai_recruiter",
)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# Lazy engine — only created when first accessed.
_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            DATABASE_URL,
            pool_size=int(os.getenv("PG_POOL_SIZE", "5")),
            max_overflow=int(os.getenv("PG_MAX_OVERFLOW", "10")),
            pool_pre_ping=True,
            echo=os.getenv("SQL_ECHO", "").lower() in ("1", "true"),
        )
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
        )
    return _SessionLocal


def SessionLocal() -> Session:
    """Create a new database session."""
    return get_session_factory()()
