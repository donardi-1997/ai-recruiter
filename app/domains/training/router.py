"""Authenticated training platform routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db, require_permission
from app.domains.training import service
from app.domains.training.schemas import (
    CreateCourseRequest,
    CreateLessonRequest,
    CreateModuleRequest,
    UpdateCourseRequest,
)


router = APIRouter(prefix="/api/training", tags=["training"])


def _translate(exc: Exception):
    if isinstance(exc, service.TrainingNotFound):
        raise HTTPException(status_code=404, detail="Contenido de capacitación no encontrado.")
    if isinstance(exc, service.TrainingAssignmentError):
        raise HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, service.TrainingStateError):
        raise HTTPException(status_code=422, detail=str(exc))
    raise exc


@router.get("/courses")
def list_courses(
    db: Session = Depends(get_db),
    _principal: dict = Depends(require_permission("training.manage")),
):
    items = service.list_courses(db)
    return {"items": items, "total": len(items)}


@router.post("/courses", status_code=201)
def create_course(
    body: CreateCourseRequest,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("training.manage")),
):
    course = service.create_course(
        db,
        title=body.title,
        description=body.description,
        created_by_sub=principal["sub"],
    )
    return service.course_payload(course, include_structure=True)


@router.get("/courses/{course_id}")
def get_course(
    course_id: str,
    db: Session = Depends(get_db),
    _principal: dict = Depends(require_permission("training.manage")),
):
    try:
        return service.get_course(db, course_id)
    except Exception as exc:
        _translate(exc)


@router.put("/courses/{course_id}")
def update_course(
    course_id: str,
    body: UpdateCourseRequest,
    db: Session = Depends(get_db),
    _principal: dict = Depends(require_permission("training.manage")),
):
    try:
        course = service.update_course(
            db,
            course_id,
            title=body.title,
            description=body.description,
            status=body.status,
        )
        return service.course_payload(course, include_structure=True)
    except Exception as exc:
        _translate(exc)


@router.post("/courses/{course_id}/modules", status_code=201)
def create_module(
    course_id: str,
    body: CreateModuleRequest,
    db: Session = Depends(get_db),
    _principal: dict = Depends(require_permission("training.manage")),
):
    try:
        service.add_module(
            db,
            course_id=course_id,
            title=body.title,
            description=body.description,
        )
        return service.get_course(db, course_id)
    except Exception as exc:
        _translate(exc)


@router.post("/modules/{module_id}/lessons", status_code=201)
def create_lesson(
    module_id: str,
    body: CreateLessonRequest,
    db: Session = Depends(get_db),
    _principal: dict = Depends(require_permission("training.manage")),
):
    try:
        lesson = service.add_lesson(
            db,
            module_id=module_id,
            title=body.title,
            description=body.description,
            video_url=body.video_url,
            duration_seconds=body.duration_seconds,
        )
        return service.get_course(db, lesson.module.course_id)
    except Exception as exc:
        _translate(exc)


@router.post("/courses/{course_id}/assignments/{employee_id}", status_code=201)
def assign_course(
    course_id: str,
    employee_id: str,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("training.assign")),
):
    try:
        assignment = service.assign_course(
            db,
            course_id=course_id,
            employee_id=employee_id,
            assigned_by_sub=principal["sub"],
        )
        return service.assignment_payload(db, assignment)
    except Exception as exc:
        _translate(exc)


@router.get("/courses/{course_id}/assignments")
def list_assignments(
    course_id: str,
    db: Session = Depends(get_db),
    _principal: dict = Depends(require_permission("training.results.read")),
):
    try:
        items = service.list_course_assignments(db, course_id)
        return {"items": items, "total": len(items)}
    except Exception as exc:
        _translate(exc)


@router.get("/me")
def my_training(
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("training.read")),
):
    items = service.list_my_training(db, principal["profile"]["id"])
    return {"items": items, "total": len(items)}


@router.get("/me/courses/{course_id}")
def my_course(
    course_id: str,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("training.read")),
):
    try:
        return service.get_my_course(
            db,
            employee_id=principal["profile"]["id"],
            course_id=course_id,
        )
    except Exception as exc:
        _translate(exc)


@router.post("/me/lessons/{lesson_id}/complete")
def complete_lesson(
    lesson_id: str,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("training.consume")),
):
    try:
        return service.complete_lesson(
            db,
            employee_id=principal["profile"]["id"],
            lesson_id=lesson_id,
        )
    except Exception as exc:
        _translate(exc)
