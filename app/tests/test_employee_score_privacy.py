"""Privacy contract for Direction-only employee scoring."""

from pathlib import Path

from app.access_control import ADMIN, SUPER_ADMIN, ROLE_PERMISSION_MATRIX


ROOT = Path(__file__).resolve().parents[2]


def test_private_score_permissions_belong_to_super_admin_only():
    score_permissions = {
        "employee_scores.read",
        "employee_scores.create",
        "employee_scores.correct",
        "employee_scores.export",
    }

    assert score_permissions.issubset(ROLE_PERMISSION_MATRIX[SUPER_ADMIN])
    assert score_permissions.isdisjoint(ROLE_PERMISSION_MATRIX[ADMIN])


def test_score_router_enforces_granular_permissions():
    text = (
        ROOT / "app" / "domains" / "employee_scores" / "router.py"
    ).read_text(encoding="utf-8")

    assert 'require_permission("employee_scores.read")' in text
    assert 'require_permission("employee_scores.create")' in text
    assert 'require_permission("employee_scores.correct")' in text


def test_general_employee_payload_does_not_expose_scores():
    text = (
        ROOT / "app" / "domains" / "employees" / "service.py"
    ).read_text(encoding="utf-8")

    start = text.index("def employee_payload")
    end = text.index("\n\ndef ", start + 1)
    payload_source = text[start:end]

    assert "score_total" not in payload_source
    assert "score_events" not in payload_source
