from app.main import app


def test_current_app_exposes_critical_routes():
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/api/jobs" in paths
    assert "/api/candidates" in paths
    assert "/api/jobs/{job_id}/ranking" in paths
    assert "/api/jobs/{job_id}/ranking/recalculate" in paths
