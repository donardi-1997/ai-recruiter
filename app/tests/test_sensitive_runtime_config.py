"""Security regression tests for runtime configuration.

Production code and deployment automation must never embed the PostgreSQL
password. Tests use SQLite through app/tests/conftest.py, so runtime code can
require DATABASE_URL without needing a production fallback.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_FILES = (
    REPO_ROOT / "app" / "db.py",
    REPO_ROOT / "scripts" / "deploy-api.sh",
    REPO_ROOT / "scripts" / "deploy-worker.sh",
    REPO_ROOT / ".github" / "workflows" / "deploy.yml",
)


def test_runtime_files_do_not_embed_postgres_password():
    offenders = []
    for path in RUNTIME_FILES:
        content = path.read_text(encoding="utf-8")
        if "postgres:postgres" in content:
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == [], (
        "Embedded PostgreSQL credentials found in: " + ", ".join(offenders)
    )


def test_application_database_url_has_no_postgres_fallback():
    content = (REPO_ROOT / "app" / "db.py").read_text(encoding="utf-8")
    assert 'os.environ["DATABASE_URL"]' in content


def test_deploy_scripts_require_database_url():
    for relative_path in ("scripts/deploy-api.sh", "scripts/deploy-worker.sh"):
        content = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert 'DATABASE_URL="${DATABASE_URL:?' in content, relative_path


def test_deploy_workflow_consumes_database_url_secret():
    content = (
        REPO_ROOT / ".github" / "workflows" / "deploy.yml"
    ).read_text(encoding="utf-8")
    assert 'DATABASE_URL: ${{ secrets.DATABASE_URL }}' in content
