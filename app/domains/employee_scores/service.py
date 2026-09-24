"""Private employee score ledger service."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.models import EmployeeScoreEvent, UserProfile


class EmployeeNotFound(Exception):
    pass


class ScoreEventNotFound(Exception):
    pass


class ScoreEventAlreadyVoided(Exception):
    pass


def require_employee(db: Session, employee_id: str) -> UserProfile:
    employee = (
        db.query(UserProfile)
        .filter(UserProfile.id == employee_id)
        .one_or_none()
    )
    if employee is None:
        raise EmployeeNotFound()
    return employee


def _employee_payload(employee: UserProfile, total: int) -> dict:
    return {
        "id": employee.id,
        "email": employee.email,
        "first_name": employee.first_name,
        "last_name": employee.last_name,
        "job_title": employee.job_title,
        "department": employee.department,
        "status": employee.status,
        "score_total": int(total or 0),
    }


def list_employee_scores(db: Session, *, q: str = "") -> list[dict]:
    active_points = case(
        (EmployeeScoreEvent.status == "ACTIVE", EmployeeScoreEvent.points),
        else_=0,
    )
    query = (
        db.query(UserProfile, func.coalesce(func.sum(active_points), 0))
        .outerjoin(
            EmployeeScoreEvent,
            EmployeeScoreEvent.employee_id == UserProfile.id,
        )
    )

    normalized_q = q.strip()
    if normalized_q:
        pattern = f"%{normalized_q}%"
        query = query.filter(
            or_(
                UserProfile.email.ilike(pattern),
                UserProfile.first_name.ilike(pattern),
                UserProfile.last_name.ilike(pattern),
                UserProfile.job_title.ilike(pattern),
                UserProfile.department.ilike(pattern),
            )
        )

    rows = (
        query.group_by(UserProfile.id)
        .order_by(UserProfile.first_name.asc(), UserProfile.last_name.asc())
        .all()
    )
    return [_employee_payload(employee, total) for employee, total in rows]


def get_employee_score(db: Session, employee_id: str) -> dict:
    employee = require_employee(db, employee_id)
    total = (
        db.query(func.coalesce(func.sum(EmployeeScoreEvent.points), 0))
        .filter(
            EmployeeScoreEvent.employee_id == employee_id,
            EmployeeScoreEvent.status == "ACTIVE",
        )
        .scalar()
    )
    return _employee_payload(employee, int(total or 0))


def event_payload(event: EmployeeScoreEvent) -> dict:
    return {
        "id": event.id,
        "employee_id": event.employee_id,
        "points": event.points,
        "description": event.description,
        "status": event.status,
        "event_date": event.event_date.isoformat() if event.event_date else None,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "created_by_sub": event.created_by_sub,
        "voided_at": event.voided_at.isoformat() if event.voided_at else None,
        "voided_by_sub": event.voided_by_sub,
        "void_reason": event.void_reason,
    }


def list_history(db: Session, employee_id: str) -> list[dict]:
    require_employee(db, employee_id)
    events = (
        db.query(EmployeeScoreEvent)
        .filter(EmployeeScoreEvent.employee_id == employee_id)
        .order_by(
            EmployeeScoreEvent.event_date.desc(),
            EmployeeScoreEvent.created_at.desc(),
        )
        .all()
    )
    return [event_payload(event) for event in events]


def add_score_event(
    db: Session,
    *,
    employee_id: str,
    points: int,
    description: str,
    created_by_sub: str,
) -> EmployeeScoreEvent:
    require_employee(db, employee_id)
    if points == 0:
        raise ValueError("points must be non-zero")

    event = EmployeeScoreEvent(
        employee_id=employee_id,
        points=points,
        description=description.strip(),
        status="ACTIVE",
        created_by_sub=created_by_sub,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def void_score_event(
    db: Session,
    *,
    event_id: str,
    reason: str,
    voided_by_sub: str,
) -> EmployeeScoreEvent:
    event = (
        db.query(EmployeeScoreEvent)
        .filter(EmployeeScoreEvent.id == event_id)
        .one_or_none()
    )
    if event is None:
        raise ScoreEventNotFound()
    if event.status == "VOIDED":
        raise ScoreEventAlreadyVoided()

    event.status = "VOIDED"
    event.voided_at = datetime.now(timezone.utc)
    event.voided_by_sub = voided_by_sub
    event.void_reason = reason.strip()
    db.commit()
    db.refresh(event)
    return event
