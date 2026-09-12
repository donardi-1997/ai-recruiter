"""Regression contract for local frontend readiness during production deploy."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_frontend_local_readiness_is_retried_before_success():
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    start = workflow.index('echo "FRONTEND_IMAGE_OK=\\$FRONTEND_IMAGE"')
    end = workflow.index('echo "DEPLOYMENT_FRONTEND_OK"', start)
    readiness = workflow[start:end]

    assert "for i in $(seq 1 10); do" in readiness
    assert "curl -fS http://127.0.0.1/" in readiness
    assert 'echo "\\$FRONTEND_HTML" | grep -q "root"' in readiness
    assert "sleep 1" in readiness
    assert "FRONTEND_READY" in readiness
