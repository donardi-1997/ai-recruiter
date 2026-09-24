"""Contract coverage for RBAC protection on recruiter-facing routes."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


ROUTE_PERMISSIONS = {
    "app/domains/jobs/router.py": "jobs.read",
    "app/domains/candidates/router.py": "candidates.read",
    "app/domains/ranking/router.py": "ranking.read",
    "app/domains/evaluations/router.py": "candidates.evaluate",
    "app/domains/candidate_imports/router.py": "candidates.evaluate",
    "app/domains/indeed/router.py": "integrations.manage",
}


def test_recruitment_routes_require_internal_permissions():
    for relative_path, permission in ROUTE_PERMISSIONS.items():
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "require_permission" in text, relative_path
        assert f'Depends(require_permission("{permission}"))' in text, relative_path
        assert "Depends(get_current_user)" not in text, relative_path
