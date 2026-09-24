from app.bootstrap import create_app
from app.main import app


def _critical_paths(application):
    return set(application.openapi()["paths"])


def test_create_app_exposes_critical_routes():
    paths = _critical_paths(create_app())
    assert "/health" in paths
    assert "/api/jobs" in paths
    assert "/api/candidates" in paths
    assert "/api/jobs/{job_id}/ranking" in paths
    assert "/api/jobs/{job_id}/ranking/recalculate" in paths
    assert "/api/integrations/indeed/status" in paths
    assert "/api/integrations/indeed/candidates/sync" in paths
    assert "/api/integrations/indeed/dispositions/sync" in paths
    assert "/api/jobs/{job_id}/integrations/indeed/publish" in paths
    assert "/api/jobs/{job_id}/integrations/indeed/status" in paths
    assert "/api/jobs/{job_id}/integrations/indeed/expire" in paths
    assert "/api/jobs/{job_id}/candidates/{candidate_id}/status" in paths
    assert "/api/jobs/{job_id}/candidates/{candidate_id}/integrations/indeed" in paths
    assert "/api/employees" in paths
    assert "/api/employees/{employee_id}" in paths
    assert "/api/employees/{employee_id}/status" in paths
    assert "/api/employees/{employee_id}/role" in paths


def test_main_app_uses_same_public_contract():
    assert _critical_paths(app) == _critical_paths(create_app())
