"""Private Direction routes for employee scoring."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.deps import get_db, require_permission
from app.domains.employee_scores import service
from app.domains.employee_scores.schemas import (
    CreateScoreEventRequest,
    VoidScoreEventRequest,
)


router = APIRouter(prefix="/api/direction/employee-scores", tags=["direction-scores"])


def _translate(exc: Exception):
    if isinstance(exc, service.EmployeeNotFound):
        raise HTTPException(status_code=404, detail="Empleado no encontrado.")
    if isinstance(exc, service.ScoreEventNotFound):
        raise HTTPException(status_code=404, detail="Movimiento no encontrado.")
    if isinstance(exc, service.ScoreEventAlreadyVoided):
        raise HTTPException(status_code=409, detail="El movimiento ya fue anulado.")
    raise exc


@router.get("")
def list_scores(
    q: str = Query("", max_length=120),
    db: Session = Depends(get_db),
    _principal: dict = Depends(require_permission("employee_scores.read")),
):
    items = service.list_employee_scores(db, q=q)
    return {"items": items, "total": len(items)}


@router.get("/{employee_id}")
def get_employee_score(
    employee_id: str,
    db: Session = Depends(get_db),
    _principal: dict = Depends(require_permission("employee_scores.read")),
):
    try:
        employee = service.get_employee_score(db, employee_id)
        history = service.list_history(db, employee_id)
        return {"employee": employee, "history": history}
    except Exception as exc:
        _translate(exc)


@router.post("/{employee_id}/events", status_code=201)
def create_score_event(
    employee_id: str,
    body: CreateScoreEventRequest,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("employee_scores.create")),
):
    try:
        event = service.add_score_event(
            db,
            employee_id=employee_id,
            points=body.points,
            description=body.description,
            created_by_sub=principal["sub"],
        )
        return {
            "event": service.event_payload(event),
            "employee": service.get_employee_score(db, employee_id),
        }
    except Exception as exc:
        _translate(exc)


@router.post("/events/{event_id}/void")
def void_score_event(
    event_id: str,
    body: VoidScoreEventRequest,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("employee_scores.correct")),
):
    try:
        event = service.void_score_event(
            db,
            event_id=event_id,
            reason=body.reason,
            voided_by_sub=principal["sub"],
        )
        return service.event_payload(event)
    except Exception as exc:
        _translate(exc)
