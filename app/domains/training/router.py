"""Authenticated training platform routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db, require_permission
from app.domains.training import service
from app.domains.training.schemas import (
    CreateCourseRequest,
    CreateLessonRequest,
    CreateLessonVideoUploadRequest,
    CreateModuleRequest,
    FinalizeLessonVideoUploadRequest,
    CreateQuizQuestionRequest,
    CreateQuizRequest,
    SubmitQuizAttemptRequest,
    UpdateChecklistProgressRequest,
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
        is_onboarding=body.is_onboarding,
    )
    return service.course_payload(course, include_structure=True)


@router.post("/courses/presets/asiati-onboarding", status_code=201)
def create_asiati_onboarding_preset(
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("training.manage")),
):
    course = service.create_asiati_onboarding_template(
        db,
        created_by_sub=principal["sub"],
    )
    return service.get_course(db, course.id)


@router.get("/courses/{course_id}/preview")
def preview_course(
    course_id: str,
    employee_id: str | None = None,
    db: Session = Depends(get_db),
    _principal: dict = Depends(require_permission("training.manage")),
):
    try:
        return service.get_course_preview(
            db,
            course_id,
            employee_id=employee_id,
        )
    except Exception as exc:
        _translate(exc)


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
            is_onboarding=body.is_onboarding,
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
            audience_job_title=body.audience_job_title,
            audience_department=body.audience_department,
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
            content_type=body.content_type,
            external_url=body.external_url,
            estimated_minutes=body.estimated_minutes,
            checklist_items=body.checklist_items,
            is_optional=body.is_optional,
        )
        return service.get_course(db, lesson.module.course_id)
    except Exception as exc:
        _translate(exc)


@router.post("/lessons/{lesson_id}/video/upload", status_code=201)
def create_lesson_video_upload(
    lesson_id: str,
    body: CreateLessonVideoUploadRequest,
    db: Session = Depends(get_db),
    _principal: dict = Depends(require_permission("training.manage")),
):
    try:
        return service.create_lesson_video_upload(
            db,
            lesson_id=lesson_id,
            filename=body.filename,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _translate(exc)


@router.post("/lessons/{lesson_id}/video/complete")
def finalize_lesson_video_upload(
    lesson_id: str,
    body: FinalizeLessonVideoUploadRequest,
    db: Session = Depends(get_db),
    _principal: dict = Depends(require_permission("training.manage")),
):
    try:
        lesson = service.finalize_lesson_video_upload(
            db,
            lesson_id=lesson_id,
            key=body.key,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
        )
        return service.get_course(db, lesson.module.course_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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


@router.put("/me/lessons/{lesson_id}/checklist")
def update_checklist_progress(
    lesson_id: str,
    body: UpdateChecklistProgressRequest,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("training.consume")),
):
    try:
        return service.update_checklist_progress(
            db,
            employee_id=principal["profile"]["id"],
            lesson_id=lesson_id,
            completed_items=body.completed_items,
        )
    except Exception as exc:
        _translate(exc)


@router.post("/courses/{course_id}/quiz", status_code=201)
def create_quiz(
    course_id: str,
    body: CreateQuizRequest,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("training.manage")),
):
    try:
        quiz = service.create_quiz(
            db,
            course_id=course_id,
            title=body.title,
            passing_score=body.passing_score,
            created_by_sub=principal["sub"],
        )
        return service.quiz_admin_payload(quiz)
    except Exception as exc:
        _translate(exc)


@router.post("/quizzes/{quiz_id}/questions", status_code=201)
def create_quiz_question(
    quiz_id: str,
    body: CreateQuizQuestionRequest,
    db: Session = Depends(get_db),
    _principal: dict = Depends(require_permission("training.manage")),
):
    try:
        question = service.add_quiz_question(
            db,
            quiz_id=quiz_id,
            prompt=body.prompt,
            options=body.options,
            correct_option=body.correct_option,
        )
        return service.quiz_admin_payload(question.quiz)
    except Exception as exc:
        _translate(exc)


@router.get("/me/courses/{course_id}/quiz")
def my_quiz(
    course_id: str,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("training.quiz.take")),
):
    try:
        return service.get_my_quiz(
            db,
            employee_id=principal["profile"]["id"],
            course_id=course_id,
        )
    except Exception as exc:
        _translate(exc)


@router.post("/me/courses/{course_id}/quiz/attempts", status_code=201)
def submit_quiz_attempt(
    course_id: str,
    body: SubmitQuizAttemptRequest,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("training.quiz.take")),
):
    try:
        return service.submit_quiz_attempt(
            db,
            employee_id=principal["profile"]["id"],
            course_id=course_id,
            answers=body.answers,
        )
    except Exception as exc:
        _translate(exc)

