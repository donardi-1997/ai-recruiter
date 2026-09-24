"""Training catalog, assignment and progress services."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    TrainingAssignment,
    TrainingCourse,
    TrainingLesson,
    TrainingLessonProgress,
    TrainingModule,
    UserProfile,
)


class TrainingNotFound(Exception):
    pass


class TrainingStateError(Exception):
    pass


class TrainingAssignmentError(Exception):
    pass


def require_course(db: Session, course_id: str) -> TrainingCourse:
    course = db.query(TrainingCourse).filter(TrainingCourse.id == course_id).one_or_none()
    if course is None:
        raise TrainingNotFound()
    return course


def require_module(db: Session, module_id: str) -> TrainingModule:
    module = db.query(TrainingModule).filter(TrainingModule.id == module_id).one_or_none()
    if module is None:
        raise TrainingNotFound()
    return module


def require_lesson(db: Session, lesson_id: str) -> TrainingLesson:
    lesson = db.query(TrainingLesson).filter(TrainingLesson.id == lesson_id).one_or_none()
    if lesson is None:
        raise TrainingNotFound()
    return lesson


def require_employee(db: Session, employee_id: str) -> UserProfile:
    employee = db.query(UserProfile).filter(UserProfile.id == employee_id).one_or_none()
    if employee is None:
        raise TrainingNotFound()
    return employee


def lesson_payload(lesson: TrainingLesson, *, completed: bool = False) -> dict:
    return {
        "id": lesson.id,
        "title": lesson.title,
        "description": lesson.description,
        "video_url": lesson.video_url,
        "duration_seconds": lesson.duration_seconds,
        "position": lesson.position,
        "completed": completed,
    }


def module_payload(module: TrainingModule, *, completed_lesson_ids: set[str] | None = None) -> dict:
    completed_lesson_ids = completed_lesson_ids or set()
    lessons = sorted(module.lessons, key=lambda lesson: lesson.position)
    return {
        "id": module.id,
        "title": module.title,
        "description": module.description,
        "position": module.position,
        "lessons": [
            lesson_payload(
                lesson,
                completed=lesson.id in completed_lesson_ids,
            )
            for lesson in lessons
        ],
    }


def _course_counts(course: TrainingCourse) -> tuple[int, int]:
    modules = list(course.modules)
    return len(modules), sum(len(module.lessons) for module in modules)


def course_payload(
    course: TrainingCourse,
    *,
    completed_lesson_ids: set[str] | None = None,
    include_structure: bool = False,
) -> dict:
    completed_lesson_ids = completed_lesson_ids or set()
    module_count, lesson_count = _course_counts(course)
    completed_count = min(len(completed_lesson_ids), lesson_count)
    progress_percent = round((completed_count / lesson_count) * 100) if lesson_count else 0

    payload = {
        "id": course.id,
        "title": course.title,
        "description": course.description,
        "status": course.status,
        "module_count": module_count,
        "lesson_count": lesson_count,
        "completed_lessons": completed_count,
        "progress_percent": progress_percent,
        "created_at": course.created_at.isoformat() if course.created_at else None,
        "updated_at": course.updated_at.isoformat() if course.updated_at else None,
    }
    if include_structure:
        payload["modules"] = [
            module_payload(
                module,
                completed_lesson_ids=completed_lesson_ids,
            )
            for module in sorted(course.modules, key=lambda item: item.position)
        ]
    return payload


def list_courses(db: Session) -> list[dict]:
    courses = db.query(TrainingCourse).order_by(TrainingCourse.created_at.desc()).all()
    return [course_payload(course) for course in courses]


def get_course(db: Session, course_id: str) -> dict:
    return course_payload(require_course(db, course_id), include_structure=True)


def create_course(
    db: Session,
    *,
    title: str,
    description: str | None,
    created_by_sub: str,
) -> TrainingCourse:
    course = TrainingCourse(
        title=title.strip(),
        description=(description or "").strip() or None,
        status="DRAFT",
        created_by_sub=created_by_sub,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


def update_course(
    db: Session,
    course_id: str,
    *,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> TrainingCourse:
    course = require_course(db, course_id)
    if title is not None:
        course.title = title.strip()
    if description is not None:
        course.description = description.strip() or None
    if status is not None:
        normalized = status.upper()
        if normalized == "PUBLISHED":
            _, lesson_count = _course_counts(course)
            if lesson_count == 0:
                raise TrainingStateError("A course needs at least one lesson before publishing.")
        course.status = normalized
    db.commit()
    db.refresh(course)
    return course


def add_module(
    db: Session,
    *,
    course_id: str,
    title: str,
    description: str | None,
) -> TrainingModule:
    course = require_course(db, course_id)
    if course.status == "ARCHIVED":
        raise TrainingStateError("Archived courses cannot be edited.")
    position = (
        db.query(func.coalesce(func.max(TrainingModule.position), 0))
        .filter(TrainingModule.course_id == course_id)
        .scalar()
        or 0
    ) + 1
    module = TrainingModule(
        course_id=course_id,
        title=title.strip(),
        description=(description or "").strip() or None,
        position=position,
    )
    db.add(module)
    db.commit()
    db.refresh(module)
    return module


def add_lesson(
    db: Session,
    *,
    module_id: str,
    title: str,
    description: str | None,
    video_url: str | None,
    duration_seconds: int | None,
) -> TrainingLesson:
    module = require_module(db, module_id)
    if module.course.status == "ARCHIVED":
        raise TrainingStateError("Archived courses cannot be edited.")
    position = (
        db.query(func.coalesce(func.max(TrainingLesson.position), 0))
        .filter(TrainingLesson.module_id == module_id)
        .scalar()
        or 0
    ) + 1
    lesson = TrainingLesson(
        module_id=module_id,
        title=title.strip(),
        description=(description or "").strip() or None,
        video_url=(video_url or "").strip() or None,
        duration_seconds=duration_seconds,
        position=position,
    )
    db.add(lesson)
    db.commit()
    db.refresh(lesson)
    return lesson


def assign_course(
    db: Session,
    *,
    course_id: str,
    employee_id: str,
    assigned_by_sub: str,
) -> TrainingAssignment:
    course = require_course(db, course_id)
    require_employee(db, employee_id)
    if course.status != "PUBLISHED":
        raise TrainingAssignmentError("Only published courses can be assigned.")

    existing = (
        db.query(TrainingAssignment)
        .filter(
            TrainingAssignment.course_id == course_id,
            TrainingAssignment.employee_id == employee_id,
        )
        .one_or_none()
    )
    if existing is not None:
        return existing

    assignment = TrainingAssignment(
        course_id=course_id,
        employee_id=employee_id,
        status="ASSIGNED",
        assigned_by_sub=assigned_by_sub,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


def _completed_ids(db: Session, assignment_id: str) -> set[str]:
    return {
        lesson_id
        for (lesson_id,) in (
            db.query(TrainingLessonProgress.lesson_id)
            .filter(
                TrainingLessonProgress.assignment_id == assignment_id,
                TrainingLessonProgress.status == "COMPLETED",
            )
            .all()
        )
    }


def assignment_payload(db: Session, assignment: TrainingAssignment) -> dict:
    completed = _completed_ids(db, assignment.id)
    course = course_payload(
        assignment.course,
        completed_lesson_ids=completed,
        include_structure=False,
    )
    return {
        "id": assignment.id,
        "status": assignment.status,
        "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None,
        "completed_at": assignment.completed_at.isoformat() if assignment.completed_at else None,
        "employee": {
            "id": assignment.employee.id,
            "email": assignment.employee.email,
            "first_name": assignment.employee.first_name,
            "last_name": assignment.employee.last_name,
            "job_title": assignment.employee.job_title,
            "department": assignment.employee.department,
        },
        "course": course,
    }


def list_course_assignments(db: Session, course_id: str) -> list[dict]:
    require_course(db, course_id)
    assignments = (
        db.query(TrainingAssignment)
        .filter(TrainingAssignment.course_id == course_id)
        .order_by(TrainingAssignment.assigned_at.desc())
        .all()
    )
    return [assignment_payload(db, assignment) for assignment in assignments]


def list_my_training(db: Session, employee_id: str) -> list[dict]:
    assignments = (
        db.query(TrainingAssignment)
        .filter(TrainingAssignment.employee_id == employee_id)
        .order_by(TrainingAssignment.assigned_at.desc())
        .all()
    )
    return [assignment_payload(db, assignment) for assignment in assignments]


def require_my_assignment(
    db: Session,
    *,
    employee_id: str,
    course_id: str,
) -> TrainingAssignment:
    assignment = (
        db.query(TrainingAssignment)
        .filter(
            TrainingAssignment.employee_id == employee_id,
            TrainingAssignment.course_id == course_id,
        )
        .one_or_none()
    )
    if assignment is None:
        raise TrainingAssignmentError("Course is not assigned to this employee.")
    return assignment


def get_my_course(db: Session, *, employee_id: str, course_id: str) -> dict:
    assignment = require_my_assignment(
        db,
        employee_id=employee_id,
        course_id=course_id,
    )
    completed = _completed_ids(db, assignment.id)
    return {
        "assignment_id": assignment.id,
        "assignment_status": assignment.status,
        "course": course_payload(
            assignment.course,
            completed_lesson_ids=completed,
            include_structure=True,
        ),
    }


def complete_lesson(
    db: Session,
    *,
    employee_id: str,
    lesson_id: str,
) -> dict:
    lesson = require_lesson(db, lesson_id)
    course = lesson.module.course
    assignment = require_my_assignment(
        db,
        employee_id=employee_id,
        course_id=course.id,
    )
    if course.status != "PUBLISHED":
        raise TrainingStateError("This course is not available.")

    existing = (
        db.query(TrainingLessonProgress)
        .filter(
            TrainingLessonProgress.assignment_id == assignment.id,
            TrainingLessonProgress.lesson_id == lesson_id,
        )
        .one_or_none()
    )
    if existing is None:
        db.add(
            TrainingLessonProgress(
                assignment_id=assignment.id,
                lesson_id=lesson_id,
                status="COMPLETED",
            )
        )
        db.flush()

    total_lessons = sum(len(module.lessons) for module in course.modules)
    completed_count = (
        db.query(TrainingLessonProgress)
        .filter(
            TrainingLessonProgress.assignment_id == assignment.id,
            TrainingLessonProgress.status == "COMPLETED",
        )
        .count()
    )
    if total_lessons and completed_count >= total_lessons:
        assignment.status = "COMPLETED"
        assignment.completed_at = datetime.now(timezone.utc)

    db.commit()
    return get_my_course(db, employee_id=employee_id, course_id=course.id)
