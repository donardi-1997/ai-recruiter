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



def test_journey_payload_exposes_next_activity_and_estimated_time(db):
    employee = _employee(db)
    course = service.create_course(
        db,
        title="Ruta",
        description=None,
        created_by_sub="admin-sub",
        is_onboarding=True,
    )
    module = service.add_module(
        db,
        course_id=course.id,
        title="Etapa 1",
        description=None,
    )
    first = service.add_lesson(
        db,
        module_id=module.id,
        title="Lectura",
        description="Lee esto",
        video_url=None,
        duration_seconds=None,
        content_type="ARTICLE",
        estimated_minutes=3,
    )
    second = service.add_lesson(
        db,
        module_id=module.id,
        title="Video",
        description=None,
        video_url="https://cdn.example.com/video.mp4",
        duration_seconds=240,
        content_type="VIDEO",
    )
    service.update_course(db, course.id, status="PUBLISHED")
    service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )

    payload = service.get_my_course(
        db,
        employee_id=employee.id,
        course_id=course.id,
    )["course"]

    assert payload["estimated_minutes"] == 7
    assert payload["remaining_minutes"] == 7
    assert payload["next_lesson_id"] == first.id
    assert payload["modules"][0]["progress_percent"] == 0

    service.complete_lesson(
        db,
        employee_id=employee.id,
        lesson_id=first.id,
    )
    payload = service.get_my_course(
        db,
        employee_id=employee.id,
        course_id=course.id,
    )["course"]

    assert payload["remaining_minutes"] == 4
    assert payload["next_lesson_id"] == second.id


def test_optional_resources_do_not_block_course_completion(db):
    employee = _employee(db)
    course = service.create_course(
        db,
        title="Ruta con recursos",
        description=None,
        created_by_sub="admin-sub",
    )
    module = service.add_module(
        db,
        course_id=course.id,
        title="Contenido",
        description=None,
    )
    required = service.add_lesson(
        db,
        module_id=module.id,
        title="Obligatoria",
        description=None,
        video_url=None,
        duration_seconds=None,
        content_type="ARTICLE",
        estimated_minutes=2,
    )
    service.add_lesson(
        db,
        module_id=module.id,
        title="Instagram",
        description=None,
        video_url=None,
        duration_seconds=None,
        content_type="RESOURCE",
        external_url="https://www.instagram.com/asiati_corp/",
        estimated_minutes=2,
        is_optional=True,
    )
    service.update_course(db, course.id, status="PUBLISHED")
    assignment = service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )

    result = service.complete_lesson(
        db,
        employee_id=employee.id,
        lesson_id=required.id,
    )

    db.refresh(assignment)
    assert assignment.status == "COMPLETED"
    assert result["course"]["lesson_count"] == 1
    assert result["course"]["content_item_count"] == 2
    assert result["course"]["progress_percent"] == 100


def test_employee_journey_hides_empty_admin_scaffold_modules(db):
    employee = _employee(db)
    course = service.create_course(
        db,
        title="Ruta limpia",
        description=None,
        created_by_sub="admin-sub",
    )
    visible = service.add_module(
        db,
        course_id=course.id,
        title="Contenido listo",
        description=None,
    )
    service.add_lesson(
        db,
        module_id=visible.id,
        title="Actividad",
        description=None,
        video_url=None,
        duration_seconds=None,
        content_type="ARTICLE",
        estimated_minutes=2,
    )
    service.add_module(
        db,
        course_id=course.id,
        title="Pendiente de configurar",
        description="Solo visible en administración hasta tener contenido.",
    )
    service.update_course(db, course.id, status="PUBLISHED")
    service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )

    employee_payload = service.get_my_course(
        db,
        employee_id=employee.id,
        course_id=course.id,
    )["course"]
    admin_payload = service.get_course(db, course.id)

    assert [module["title"] for module in employee_payload["modules"]] == [
        "Contenido listo",
    ]
    assert [module["title"] for module in admin_payload["modules"]] == [
        "Contenido listo",
        "Pendiente de configurar",
    ]


def test_employee_journey_hides_video_placeholders_without_media(db):
    employee = _employee(db)
    course = service.create_course(
        db,
        title="Ruta con video pendiente",
        description=None,
        created_by_sub="admin-sub",
    )
    module = service.add_module(
        db,
        course_id=course.id,
        title="Videos",
        description=None,
    )
    pending = service.add_lesson(
        db,
        module_id=module.id,
        title="Módulo 1 · ASIATI",
        description=None,
        video_url=None,
        duration_seconds=None,
        content_type="VIDEO",
        estimated_minutes=None,
    )
    ready = service.add_lesson(
        db,
        module_id=module.id,
        title="Video listo",
        description=None,
        video_url="https://example.com/video.mp4",
        duration_seconds=60,
        content_type="VIDEO",
        estimated_minutes=1,
    )
    service.update_course(db, course.id, status="PUBLISHED")
    service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )

    payload = service.get_my_course(
        db,
        employee_id=employee.id,
        course_id=course.id,
    )["course"]

    assert payload["lesson_count"] == 1
    assert payload["content_item_count"] == 1
    assert payload["next_lesson_id"] == ready.id
    assert [lesson["id"] for lesson in payload["modules"][0]["lessons"]] == [
        ready.id,
    ]

    with pytest.raises(service.TrainingStateError):
        service.complete_lesson(
            db,
            employee_id=employee.id,
            lesson_id=pending.id,
        )


def test_checklist_progress_is_persisted_and_resumed(db):
    employee = _employee(db)
    course = service.create_course(
        db,
        title="Primeros días",
        description=None,
        created_by_sub="admin-sub",
    )
    module = service.add_module(
        db,
        course_id=course.id,
        title="Tu cargo",
        description=None,
    )
    checklist = service.add_lesson(
        db,
        module_id=module.id,
        title="Checklist inicial",
        description=None,
        video_url=None,
        duration_seconds=None,
        content_type="CHECKLIST",
        estimated_minutes=3,
        checklist_items=[
            "Conozco mi alcance.",
            "Tengo mis accesos.",
            "Sé quién es mi líder.",
        ],
    )
    service.update_course(db, course.id, status="PUBLISHED")
    assignment = service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )

    partial = service.update_checklist_progress(
        db,
        employee_id=employee.id,
        lesson_id=checklist.id,
        completed_items=[0, 2],
    )

    lesson_payload = partial["course"]["modules"][0]["lessons"][0]
    assert lesson_payload["completed"] is False
    assert lesson_payload["checklist_completed_items"] == [0, 2]
    assert partial["course"]["progress_percent"] == 0

    restored = service.get_my_course(
        db,
        employee_id=employee.id,
        course_id=course.id,
    )
    restored_lesson = restored["course"]["modules"][0]["lessons"][0]
    assert restored_lesson["checklist_completed_items"] == [0, 2]

    completed = service.update_checklist_progress(
        db,
        employee_id=employee.id,
        lesson_id=checklist.id,
        completed_items=[0, 1, 2],
    )

    db.refresh(assignment)
    assert assignment.status == "COMPLETED"
    assert completed["course"]["progress_percent"] == 100
    assert completed["course"]["completed_lessons"] == 1
    assert completed["course"]["modules"][0]["lessons"][0]["completed"] is True


def test_checklist_progress_rejects_invalid_item_index(db):
    employee = _employee(db)
    course = service.create_course(
        db,
        title="Checklist inválido",
        description=None,
        created_by_sub="admin-sub",
    )
    module = service.add_module(
        db,
        course_id=course.id,
        title="Contenido",
        description=None,
    )
    checklist = service.add_lesson(
        db,
        module_id=module.id,
        title="Checklist",
        description=None,
        video_url=None,
        duration_seconds=None,
        content_type="CHECKLIST",
        checklist_items=["Uno", "Dos"],
    )
    service.update_course(db, course.id, status="PUBLISHED")
    service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )

    with pytest.raises(service.TrainingStateError):
        service.update_checklist_progress(
            db,
            employee_id=employee.id,
            lesson_id=checklist.id,
            completed_items=[0, 2],
        )


def test_role_targeted_modules_are_filtered_for_employee(db):
    employee = _employee(db)
    employee.job_title = "Comercial"
    employee.department = "Ventas"
    db.commit()

    course = service.create_course(
        db,
        title="Ruta por cargo",
        description=None,
        created_by_sub="admin-sub",
    )
    common = service.add_module(
        db,
        course_id=course.id,
        title="Común",
        description=None,
    )
    service.add_lesson(
        db,
        module_id=common.id,
        title="General",
        description=None,
        video_url=None,
        duration_seconds=None,
        content_type="ARTICLE",
        estimated_minutes=1,
    )
    sales = service.add_module(
        db,
        course_id=course.id,
        title="Ventas",
        description=None,
        audience_job_title="Comercial",
        audience_department="Ventas",
    )
    service.add_lesson(
        db,
        module_id=sales.id,
        title="CRM",
        description=None,
        video_url=None,
        duration_seconds=None,
        content_type="CHECKLIST",
        estimated_minutes=2,
    )
    dev = service.add_module(
        db,
        course_id=course.id,
        title="Desarrollo",
        description=None,
        audience_job_title="Desarrollador",
    )
    service.add_lesson(
        db,
        module_id=dev.id,
        title="Git",
        description=None,
        video_url=None,
        duration_seconds=None,
        content_type="CHECKLIST",
        estimated_minutes=2,
    )
    service.update_course(db, course.id, status="PUBLISHED")
    service.assign_course(
        db,
        course_id=course.id,
        employee_id=employee.id,
        assigned_by_sub="admin-sub",
    )

    payload = service.get_my_course(
        db,
        employee_id=employee.id,
        course_id=course.id,
    )["course"]

    assert [module["title"] for module in payload["modules"]] == ["Común", "Ventas"]
    assert payload["lesson_count"] == 2
    assert payload["estimated_minutes"] == 3


def test_asiati_onboarding_template_repairs_existing_draft_without_duplicate(db):
    course = service.create_course(
        db,
        title="Onboarding ASIATI",
        description="Versión existente",
        created_by_sub="admin-sub",
        is_onboarding=True,
    )
    service.add_module(
        db,
        course_id=course.id,
        title="Evaluación final",
        description="Placeholder anterior",
    )

    repaired = service.create_asiati_onboarding_template(
        db,
        created_by_sub="admin-sub",
    )
    payload = service.get_course(db, repaired.id)

    assert repaired.id == course.id
    assert all(
        module["title"] != "Evaluación final"
        for module in payload["modules"]
    )
    assert payload["quiz"]["title"] == "Evaluación final"
    assert payload["quiz"]["passing_score"] == 70
    assert payload["quiz"]["question_count"] == 5


def test_asiati_onboarding_template_scaffolds_short_journey(db):
    course = service.create_asiati_onboarding_template(
        db,
        created_by_sub="admin-sub",
    )

    payload = service.get_course(db, course.id)

    assert payload["status"] == "DRAFT"
    assert payload["is_onboarding"] is True
    assert [module["title"] for module in payload["modules"]] == [
        "Bienvenida",
        "Conoce ASIATI",
        "Nuestro ecosistema",
        "Así trabajamos",
        "Tu cargo en ASIATI",
    ]
    assert payload["quiz"]["title"] == "Evaluación final"
    assert payload["quiz"]["passing_score"] == 70
    assert payload["quiz"]["question_count"] == 5
    assert payload["quiz"]["questions"][0]["prompt"].startswith(
        "¿Cuál es el sitio web corporativo oficial"
    )

    role_checklist = next(
        lesson
        for module in payload["modules"]
        for lesson in module["lessons"]
        if lesson["title"] == "Tu rol y tus primeros días"
    )
    assert role_checklist["content_type"] == "CHECKLIST"
    assert role_checklist["checklist_items"] == service.ASIATI_ROLE_CHECKLIST_ITEMS

    resources = [
        lesson
        for module in payload["modules"]
        for lesson in module["lessons"]
        if lesson["content_type"] == "RESOURCE"
    ]
    assert any(
        lesson["external_url"] == "https://www.asiaticorp.com/"
        for lesson in resources
    )
    assert any(
        "canva.link" in str(lesson["external_url"])
        for lesson in resources
    )
    assert any(
        lesson["title"] == "El Retrovisor"
        for lesson in resources
    )

    video_titles = [
        lesson["title"]
        for module in payload["modules"]
        for lesson in module["lessons"]
        if lesson["content_type"] == "VIDEO"
    ]
    assert "Módulo 1 · ASIATI" in video_titles
    assert "Módulo 2 · ASIATI" in video_titles
    assert "Módulo 3 · ASIATI" in video_titles
    assert "Módulos 1–3 · Introducción corporativa" not in video_titles
    assert "Módulo 4 · Permisos y vacaciones" in video_titles
    assert "Módulo 5 · Recorrido de sede" in video_titles
    assert "Módulo 6 · Cultura interna" in video_titles
    assert "Módulo 7 · Lo que esperamos de ti" in video_titles

    split_lessons = [
        lesson
        for module in payload["modules"]
        for lesson in module["lessons"]
        if lesson["title"] in {
            "Módulo 1 · ASIATI",
            "Módulo 2 · ASIATI",
            "Módulo 3 · ASIATI",
        }
    ]
    assert len(split_lessons) == 3
    assert all(lesson["video_url"] is None for lesson in split_lessons)
    assert all(lesson["estimated_minutes"] is None for lesson in split_lessons)
    assert all(lesson["duration_known"] is False for lesson in split_lessons)


def test_onboarding_quality_report_flags_heavy_or_incomplete_content(db):
    course = service.create_course(
        db,
        title="Onboarding pesado",
        description=None,
        created_by_sub="admin-sub",
        is_onboarding=True,
    )
    module = service.add_module(
        db,
        course_id=course.id,
        title="Contenido",
        description=None,
    )
    service.add_lesson(
        db,
        module_id=module.id,
        title="Lectura extensa",
        description=None,
        video_url=None,
        duration_seconds=None,
        content_type="ARTICLE",
        estimated_minutes=9,
    )
    service.add_lesson(
        db,
        module_id=module.id,
        title="Video pendiente",
        description=None,
        video_url=None,
        duration_seconds=None,
        content_type="VIDEO",
        estimated_minutes=None,
    )
    quiz = service.create_quiz(
        db,
        course_id=course.id,
        title="Evaluación final",
        passing_score=70,
        created_by_sub="admin-sub",
    )
    for index in range(2):
        service.add_quiz_question(
            db,
            quiz_id=quiz.id,
            prompt=f"Pregunta {index + 1}",
            options=["A", "B"],
            correct_option=0,
        )

    report = service.course_quality_report(course)
    codes = {issue["code"] for issue in report["issues"]}

    assert report["required_activity_count"] == 2
    assert report["known_minutes"] == 9
    assert report["quiz_question_count"] == 2
    assert {
        "LONG_ACTIVITY",
        "UNKNOWN_DURATION",
        "MISSING_VIDEO",
        "QUIZ_TOO_SHORT",
    }.issubset(codes)


def test_course_preview_respects_employee_role_and_department(db):
    employee = _employee(db)
    employee.first_name = "Laura"
    employee.job_title = "Comercial"
    employee.department = "Ventas"
    db.commit()

    course = service.create_course(
        db,
        title="Ruta segmentada",
        description=None,
        created_by_sub="admin-sub",
        is_onboarding=True,
    )
    common = service.add_module(
        db,
        course_id=course.id,
        title="Común",
        description=None,
    )
    service.add_lesson(
        db,
        module_id=common.id,
        title="General",
        description=None,
        video_url=None,
        duration_seconds=None,
        content_type="ARTICLE",
        estimated_minutes=2,
    )
    sales = service.add_module(
        db,
        course_id=course.id,
        title="Ventas",
        description=None,
        audience_job_title="Comercial",
        audience_department="Ventas",
    )
    service.add_lesson(
        db,
        module_id=sales.id,
        title="CRM",
        description=None,
        video_url=None,
        duration_seconds=None,
        content_type="CHECKLIST",
        estimated_minutes=3,
    )
    dev = service.add_module(
        db,
        course_id=course.id,
        title="Desarrollo",
        description=None,
        audience_job_title="Desarrollador",
    )
    service.add_lesson(
        db,
        module_id=dev.id,
        title="Git",
        description=None,
        video_url=None,
        duration_seconds=None,
        content_type="ARTICLE",
        estimated_minutes=3,
    )

    preview = service.get_course_preview(
        db,
        course.id,
        employee_id=employee.id,
    )

    assert [module["title"] for module in preview["modules"]] == [
        "Común",
        "Ventas",
    ]
    assert preview["preview_employee"]["id"] == employee.id
    assert preview["preview_employee"]["job_title"] == "Comercial"
    assert preview["quality"]["required_activity_count"] == 2
    assert preview["quality"]["known_minutes"] == 5

