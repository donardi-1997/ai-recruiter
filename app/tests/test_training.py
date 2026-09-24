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
    TrainingQuizAttempt,
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



def _published_course_with_quiz(db):
    course = service.create_course(
        db,
        title="Inducción con evaluación",
        description="Curso con quiz",
        created_by_sub="admin-sub",
    )
    module = service.add_module(
        db,
        course_id=course.id,
        title="Bienvenida",
        description=None,
    )
    lesson = service.add_lesson(
        db,
        module_id=module.id,
        title="Lección base",
        description=None,
        video_url=None,
        duration_seconds=None,
    )
    quiz = service.create_quiz(
        db,
        course_id=course.id,
        title="Evaluación final",
        passing_score=70,
        created_by_sub="admin-sub",
    )
    question = service.add_quiz_question(
        db,
        quiz_id=quiz.id,
        prompt="¿Cuál es la respuesta correcta?",
        options=["A", "B", "C"],
        correct_option=1,
    )
    service.update_course(db, course.id, status="PUBLISHED")
    return course, lesson, quiz, question


def test_course_with_empty_quiz_cannot_publish(db):
    course = service.create_course(
        db,
        title="Curso",
        description=None,
        created_by_sub="admin-sub",
    )
    module = service.add_module(
        db,
        course_id=course.id,
        title="Módulo",
        description=None,
    )
    service.add_lesson(
        db,
        module_id=module.id,
        title="Lección",
        description=None,
        video_url=None,
        duration_seconds=None,
    )
    service.create_quiz(
        db,
        course_id=course.id,
        title="Quiz",
        passing_score=80,
        created_by_sub="admin-sub",
    )

    with pytest.raises(service.TrainingStateError):
        service.update_course(db, course.id, status="PUBLISHED")


def test_quiz_correct_answer_is_not_exposed_to_employee(db):
    employee = _employee(db)
    course, lesson, _, question = _published_course_with_quiz(db)
    assignment = service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )

    service.complete_lesson(db, employee_id=employee.id, lesson_id=lesson.id)
    db.refresh(assignment)

    payload = service.get_my_quiz(
        db,
        employee_id=employee.id,
        course_id=course.id,
    )

    assert assignment.status == "ASSIGNED"
    assert payload["questions"][0]["id"] == question.id
    assert "correct_option" not in payload["questions"][0]


def test_quiz_requires_all_lessons_completed(db):
    employee = _employee(db)
    course, _, _, _ = _published_course_with_quiz(db)
    service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )

    with pytest.raises(service.TrainingStateError):
        service.get_my_quiz(
            db,
            employee_id=employee.id,
            course_id=course.id,
        )


def test_failed_quiz_attempt_keeps_assignment_open(db):
    employee = _employee(db)
    course, lesson, _, question = _published_course_with_quiz(db)
    assignment = service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )
    service.complete_lesson(db, employee_id=employee.id, lesson_id=lesson.id)

    result = service.submit_quiz_attempt(
        db,
        employee_id=employee.id,
        course_id=course.id,
        answers={question.id: 0},
    )

    db.refresh(assignment)
    assert result["attempt"]["score_percent"] == 0
    assert result["attempt"]["passed"] is False
    assert assignment.status == "ASSIGNED"
    assert assignment.completed_at is None


def test_passing_quiz_attempt_completes_assignment_and_keeps_attempt_history(db):
    employee = _employee(db)
    course, lesson, _, question = _published_course_with_quiz(db)
    assignment = service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )
    service.complete_lesson(db, employee_id=employee.id, lesson_id=lesson.id)

    first = service.submit_quiz_attempt(
        db,
        employee_id=employee.id,
        course_id=course.id,
        answers={question.id: 0},
    )
    second = service.submit_quiz_attempt(
        db,
        employee_id=employee.id,
        course_id=course.id,
        answers={question.id: 1},
    )

    db.refresh(assignment)
    payload = service.assignment_payload(db, assignment)

    assert first["attempt"]["attempt_number"] == 1
    assert second["attempt"]["attempt_number"] == 2
    assert second["attempt"]["score_percent"] == 100
    assert second["attempt"]["passed"] is True
    assert assignment.status == "COMPLETED"
    assert assignment.completed_at is not None
    assert db.query(TrainingQuizAttempt).count() == 2
    assert payload["quiz_result"] == {
        "attempt_count": 2,
        "best_score": 100,
        "latest_score": 100,
        "passed": True,
    }


def test_quiz_submission_requires_every_question(db):
    employee = _employee(db)
    course, lesson, _, _ = _published_course_with_quiz(db)
    service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )
    service.complete_lesson(db, employee_id=employee.id, lesson_id=lesson.id)

    with pytest.raises(service.TrainingStateError):
        service.submit_quiz_attempt(
            db,
            employee_id=employee.id,
            course_id=course.id,
            answers={},
        )



def test_managed_video_finalize_persists_metadata_and_replaces_external_url(
    db,
    monkeypatch,
):
    course = service.create_course(
        db,
        title="Curso video",
        description=None,
        created_by_sub="admin-sub",
    )
    module = service.add_module(
        db,
        course_id=course.id,
        title="Modulo",
        description=None,
    )
    lesson = service.add_lesson(
        db,
        module_id=module.id,
        title="Video",
        description=None,
        video_url="https://example.com/old.mp4",
        duration_seconds=120,
    )

    monkeypatch.setattr(
        service.training_media,
        "verify_video_object",
        lambda **kwargs: {
            "key": kwargs["key"],
            "content_type": kwargs["expected_content_type"],
            "size_bytes": kwargs["expected_size_bytes"],
        },
    )
    monkeypatch.setattr(
        service.training_media,
        "delete_video_object",
        lambda key: None,
    )

    updated = service.finalize_lesson_video_upload(
        db,
        lesson_id=lesson.id,
        key=f"training/lessons/{lesson.id}/video.mp4",
        content_type="video/mp4",
        size_bytes=1234,
    )

    assert updated.video_url is None
    assert updated.video_storage_key.endswith("/video.mp4")
    assert updated.video_content_type == "video/mp4"
    assert updated.video_size_bytes == 1234


def test_managed_video_payload_uses_temporary_playback_url(db, monkeypatch):
    course = service.create_course(
        db,
        title="Curso playback",
        description=None,
        created_by_sub="admin-sub",
    )
    module = service.add_module(
        db,
        course_id=course.id,
        title="Modulo",
        description=None,
    )
    lesson = service.add_lesson(
        db,
        module_id=module.id,
        title="Video",
        description=None,
        video_url=None,
        duration_seconds=60,
    )
    lesson.video_storage_key = f"training/lessons/{lesson.id}/video.mp4"
    lesson.video_content_type = "video/mp4"
    lesson.video_size_bytes = 4321
    db.commit()
    db.refresh(lesson)

    monkeypatch.setattr(
        service.training_media,
        "create_video_playback_url",
        lambda key: f"https://signed.example/{key}",
    )

    payload = service.lesson_payload(lesson)

    assert payload["video_source"] == "managed"
    assert payload["video_url"].startswith("https://signed.example/")
    assert payload["video_content_type"] == "video/mp4"
    assert payload["video_size_bytes"] == 4321


def test_published_course_rejects_new_video_upload(db):
    course, _, lesson = _published_course(db)

    with pytest.raises(service.TrainingStateError):
        service.create_lesson_video_upload(
            db,
            lesson_id=lesson.id,
            filename="video.mp4",
            content_type="video/mp4",
            size_bytes=100,
        )



def _published_onboarding_course(db, *, with_quiz=False):
    course = service.create_course(
        db,
        title="Inducción ASIATI",
        description="Onboarding",
        created_by_sub="admin-sub",
        is_onboarding=True,
    )
    module = service.add_module(
        db,
        course_id=course.id,
        title="Bienvenida",
        description=None,
    )
    lesson = service.add_lesson(
        db,
        module_id=module.id,
        title="Nuestra empresa",
        description=None,
        video_url=None,
        duration_seconds=None,
    )
    question = None
    if with_quiz:
        quiz = service.create_quiz(
            db,
            course_id=course.id,
            title="Evaluación",
            passing_score=70,
            created_by_sub="admin-sub",
        )
        question = service.add_quiz_question(
            db,
            quiz_id=quiz.id,
            prompt="¿Entendiste la inducción?",
            options=["No", "Sí"],
            correct_option=1,
        )
    service.update_course(db, course.id, status="PUBLISHED")
    return course, lesson, question


def test_onboarding_assignment_moves_employee_to_in_progress(db):
    employee = _employee(db)
    assert employee.onboarding_status == "PENDING"
    course, _, _ = _published_onboarding_course(db)

    service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )

    db.refresh(employee)
    assert employee.onboarding_status == "IN_PROGRESS"
    assert employee.onboarding_started_at is not None
    assert employee.onboarding_completed_at is None


def test_onboarding_without_quiz_completes_with_last_lesson(db):
    employee = _employee(db)
    course, lesson, _ = _published_onboarding_course(db)
    service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )

    service.complete_lesson(
        db,
        employee_id=employee.id,
        lesson_id=lesson.id,
    )

    db.refresh(employee)
    assert employee.onboarding_status == "COMPLETED"
    assert employee.onboarding_completed_at is not None


def test_onboarding_with_quiz_completes_only_after_passing(db):
    employee = _employee(db)
    course, lesson, question = _published_onboarding_course(db, with_quiz=True)
    service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )
    service.complete_lesson(
        db,
        employee_id=employee.id,
        lesson_id=lesson.id,
    )

    db.refresh(employee)
    assert employee.onboarding_status == "IN_PROGRESS"

    service.submit_quiz_attempt(
        db,
        employee_id=employee.id,
        course_id=course.id,
        answers={question.id: 0},
    )
    db.refresh(employee)
    assert employee.onboarding_status == "IN_PROGRESS"

    service.submit_quiz_attempt(
        db,
        employee_id=employee.id,
        course_id=course.id,
        answers={question.id: 1},
    )
    db.refresh(employee)
    assert employee.onboarding_status == "COMPLETED"
    assert employee.onboarding_completed_at is not None


def test_onboarding_waits_for_all_assigned_onboarding_courses(db):
    employee = _employee(db)
    first_course, first_lesson, _ = _published_onboarding_course(db)

    second_course = service.create_course(
        db,
        title="Seguridad ASIATI",
        description="Segundo onboarding",
        created_by_sub="admin-sub",
        is_onboarding=True,
    )
    module = service.add_module(
        db,
        course_id=second_course.id,
        title="Seguridad",
        description=None,
    )
    second_lesson = service.add_lesson(
        db,
        module_id=module.id,
        title="Políticas",
        description=None,
        video_url=None,
        duration_seconds=None,
    )
    service.update_course(db, second_course.id, status="PUBLISHED")

    service.assign_course(
        db,
        course_id=first_course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )
    service.assign_course(
        db,
        course_id=second_course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )

    service.complete_lesson(db, employee_id=employee.id, lesson_id=first_lesson.id)
    db.refresh(employee)
    assert employee.onboarding_status == "IN_PROGRESS"

    service.complete_lesson(db, employee_id=employee.id, lesson_id=second_lesson.id)
    db.refresh(employee)
    assert employee.onboarding_status == "COMPLETED"


def test_course_payload_exposes_onboarding_classification(db):
    course, _, _ = _published_onboarding_course(db)

    payload = service.get_course(db, course.id)

    assert payload["is_onboarding"] is True
