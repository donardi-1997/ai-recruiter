"""Private employee score ledger coverage."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.domains.employee_scores import service
from app.models import EmployeeScoreEvent, UserProfile


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return engine, Session()


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


def test_score_total_is_sum_of_active_ledger_events():
    engine, db = _session()
    try:
        employee = _employee(db)
        service.add_score_event(
            db,
            employee_id=employee.id,
            points=30,
            description="Completó el proyecto de integración.",
            created_by_sub="director-sub",
        )
        service.add_score_event(
            db,
            employee_id=employee.id,
            points=-5,
            description="Ausencia registrada.",
            created_by_sub="director-sub",
        )

        score = service.get_employee_score(db, employee.id)
        history = service.list_history(db, employee.id)

        assert score["score_total"] == 25
        assert [event["points"] for event in history] == [-5, 30]
        assert history[0]["description"] == "Ausencia registrada."
    finally:
        db.close()
        engine.dispose()


def test_voiding_event_keeps_history_and_removes_points_from_total():
    engine, db = _session()
    try:
        employee = _employee(db)
        positive = service.add_score_event(
            db,
            employee_id=employee.id,
            points=30,
            description="Proyecto completado.",
            created_by_sub="director-sub",
        )
        negative = service.add_score_event(
            db,
            employee_id=employee.id,
            points=-5,
            description="Ausencia.",
            created_by_sub="director-sub",
        )

        service.void_score_event(
            db,
            event_id=negative.id,
            reason="Registro realizado por error.",
            voided_by_sub="director-sub",
        )

        score = service.get_employee_score(db, employee.id)
        history = service.list_history(db, employee.id)
        voided = next(item for item in history if item["id"] == negative.id)

        assert score["score_total"] == 30
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "Registro realizado por error."
        assert any(item["id"] == positive.id for item in history)
    finally:
        db.close()
        engine.dispose()


def test_list_employee_scores_does_not_drop_zero_score_employees():
    engine, db = _session()
    try:
        employee = _employee(db)
        items = service.list_employee_scores(db)

        assert len(items) == 1
        assert items[0]["id"] == employee.id
        assert items[0]["score_total"] == 0
    finally:
        db.close()
        engine.dispose()


def test_score_event_model_rejects_zero_via_service():
    engine, db = _session()
    try:
        employee = _employee(db)
        try:
            service.add_score_event(
                db,
                employee_id=employee.id,
                points=0,
                description="No debe guardarse.",
                created_by_sub="director-sub",
            )
        except ValueError as exc:
            assert "non-zero" in str(exc)
        else:
            raise AssertionError("zero-point event was accepted")

        assert db.query(EmployeeScoreEvent).count() == 0
    finally:
        db.close()
        engine.dispose()
