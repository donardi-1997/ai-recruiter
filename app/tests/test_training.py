"""Unit coverage for internal training courses and progress."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.domains.training import service
from app.models import (
    TrainingAssignment,
    TrainingCourse,
    TrainingLesson,
    TrainingLessonProgress,
    TrainingModule,
    UserProfile,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _employee(db, email="employee@asiati.com.co"):
    employee = UserProfile(
        cognito_sub=f"sub-{email}",
        email=email,
        first_name="Ana",
        last_name="Pérez",
        job_title="Comercial",
        department="Ventas",
        status="ACTIVE",
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def _published_course(db):
    course = service.create_course(
        db,
        title="Inducción ASIATI",
        description="Curso base",
        created_by_sub="admin-sub",
    )
    module = service.add_module(
        db,
        course_id=course.id,
        title="Bienvenida",
        description="Primer módulo",
    )
    lesson = service.add_lesson(
        db,
        module_id=module.id,
        title="Quiénes somos",
        description="Contexto de la empresa",
        video_url="https://cdn.example.com/intro.mp4",
        duration_seconds=120,
    )
    service.update_course(
        db,
        course.id,
        status="PUBLISHED",
    )
    return course, module, lesson


def test_course_requires_lesson_before_publish(db):
    course = service.create_course(
        db,
        title="Curso vacío",
        description=None,
        created_by_sub="admin-sub",
    )

    with pytest.raises(service.TrainingStateError):
        service.update_course(db, course.id, status="PUBLISHED")

    db.refresh(course)
    assert course.status == "DRAFT"


def test_admin_can_build_and_publish_course(db):
    course, module, lesson = _published_course(db)

    payload = service.get_course(db, course.id)

    assert payload["status"] == "PUBLISHED"
    assert payload["module_count"] == 1
    assert payload["lesson_count"] == 1
    assert payload["modules"][0]["id"] == module.id
    assert payload["modules"][0]["lessons"][0]["id"] == lesson.id
    assert payload["modules"][0]["lessons"][0]["video_url"].startswith("https://")


def test_only_published_course_can_be_assigned(db):
    employee = _employee(db)
    course = service.create_course(
        db,
        title="Borrador",
        description=None,
        created_by_sub="admin-sub",
    )

    with pytest.raises(service.TrainingAssignmentError):
        service.assign_course(
            db,
            course_id=course.id,
            employee_id=employee.id,
            assigned_by_sub="admin-sub",
        )


def test_assignment_is_idempotent_and_employee_sees_only_assigned_course(db):
    employee = _employee(db)
    course, _, _ = _published_course(db)

    first = service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )
    second = service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )

    items = service.list_my_training(db, employee.id)

    assert first.id == second.id
    assert db.query(TrainingAssignment).count() == 1
    assert len(items) == 1
    assert items[0]["course"]["id"] == course.id
    assert items[0]["course"]["progress_percent"] == 0


def test_completing_last_lesson_marks_assignment_completed(db):
    employee = _employee(db)
    course, _, lesson = _published_course(db)
    assignment = service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )

    result = service.complete_lesson(
        db,
        employee_id=employee.id,
        lesson_id=lesson.id,
    )

    db.refresh(assignment)
    assert assignment.status == "COMPLETED"
    assert assignment.completed_at is not None
    assert result["course"]["progress_percent"] == 100
    assert result["course"]["completed_lessons"] == 1
    assert result["course"]["modules"][0]["lessons"][0]["completed"] is True


def test_lesson_completion_is_idempotent(db):
    employee = _employee(db)
    _, _, lesson = _published_course(db)
    service.assign_course(
        db,
        course_id=lesson.module.course_id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )

    service.complete_lesson(db, employee_id=employee.id, lesson_id=lesson.id)
    service.complete_lesson(db, employee_id=employee.id, lesson_id=lesson.id)

    assert db.query(TrainingLessonProgress).count() == 1


def test_employee_cannot_open_unassigned_course(db):
    employee = _employee(db)
    course, _, _ = _published_course(db)

    with pytest.raises(service.TrainingNotFound):
        service.get_my_course(
            db,
            employee_id=employee.id,
            course_id=course.id,
        )


def test_training_tables_are_registered_in_orm():
    assert TrainingCourse.__tablename__ in Base.metadata.tables
    assert TrainingModule.__tablename__ in Base.metadata.tables
    assert TrainingLesson.__tablename__ in Base.metadata.tables


def test_published_course_content_is_frozen(db):
    course, module, _ = _published_course(db)

    with pytest.raises(service.TrainingStateError):
        service.add_module(
            db,
            course_id=course.id,
            title="Cambio tardío",
            description=None,
        )

    with pytest.raises(service.TrainingStateError):
        service.add_lesson(
            db,
            module_id=module.id,
            title="Cambio tardío",
            description=None,
            video_url=None,
            duration_seconds=None,
        )


def test_disabled_employee_cannot_receive_new_assignment(db):
    employee = _employee(db)
    employee.status = "DISABLED"
    db.commit()
    course, _, _ = _published_course(db)

    with pytest.raises(service.TrainingAssignmentError):
        service.assign_course(
            db,
            course_id=course.id,
            employee_id=employee.id,
            assigned_by_sub="admin-sub",
        )


def test_published_course_cannot_return_to_draft(db):
    course, _, _ = _published_course(db)

    with pytest.raises(service.TrainingStateError):
        service.update_course(db, course.id, status="DRAFT")


def test_repeated_completion_preserves_course_completion_timestamp(db):
    employee = _employee(db)
    course, _, lesson = _published_course(db)
    assignment = service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )

    service.complete_lesson(db, employee_id=employee.id, lesson_id=lesson.id)
    db.refresh(assignment)
    first_completed_at = assignment.completed_at

    service.complete_lesson(db, employee_id=employee.id, lesson_id=lesson.id)
    db.refresh(assignment)

    assert assignment.completed_at == first_completed_at
