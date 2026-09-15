"""Regression coverage for the production Lightsail deploy target."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy.yml"


def test_deploy_targets_current_production_micro_instance():
    workflow = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert "INSTANCE_NAME: ai-recruiter-micro-canary" in workflow
    assert "INSTANCE_NAME: ai-recruiter\n" not in workflow


def test_deploy_does_not_require_aws_cli_on_lightsail_host():
    workflow = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    # The Micro host intentionally does not need AWS CLI. ECR credentials must
    # be generated on the GitHub runner and streamed to remote docker login.
    assert 'aws ecr get-login-password --region "$AWS_REGION" | \\\n              sudo docker login' not in workflow
    assert workflow.count('aws ecr get-login-password --region "$AWS_REGION" | \\\n            ssh ') == 2
