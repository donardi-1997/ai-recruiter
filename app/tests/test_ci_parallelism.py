"""Contracts for safe parallel execution of backend CI tests."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"


def test_pull_request_backend_suite_uses_file_scoped_xdist_workers():
    workflow = CI.read_text(encoding="utf-8")
    assert "pytest-xdist" in workflow
    assert "-n 2 --dist=loadfile" in workflow


def test_production_backend_gate_uses_same_parallel_strategy():
    workflow = DEPLOY.read_text(encoding="utf-8")
    assert "pytest-xdist" in workflow
    assert "-n 2 --dist=loadfile" in workflow


def test_postgres_smoke_does_not_wait_for_sqlite_suite():
    workflow = CI.read_text(encoding="utf-8")
    smoke_block = workflow.split("backend-smoke:", 1)[1].split("frontend:", 1)[0]
    assert "needs: backend-tests" not in smoke_block
