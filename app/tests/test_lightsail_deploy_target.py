"""Regression coverage for the production Lightsail deploy target."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy.yml"


def test_deploy_targets_current_production_micro_instance():
    workflow = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert "INSTANCE_NAME: ai-recruiter-micro-prod" in workflow
    assert "INSTANCE_NAME: ai-recruiter-micro-canary" not in workflow
