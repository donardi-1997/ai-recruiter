"""Contracts that keep PR validation and production deploy triggers separate."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEPLOY_YML = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
AGENT_YML = REPO_ROOT / ".github" / "workflows" / "indeed-resume-agent.yml"


def test_ci_workflow_is_the_only_pull_request_validation_entrypoint():
    ci_text = CI_YML.read_text(encoding="utf-8")
    deploy_text = DEPLOY_YML.read_text(encoding="utf-8")
    agent_text = AGENT_YML.read_text(encoding="utf-8")

    assert "pull_request:" in ci_text
    assert "pull_request:" not in deploy_text
    assert "pull_request:" not in agent_text
    assert "push:" in agent_text
    assert "branches: [main]" in agent_text
    assert "workflow_dispatch:" in agent_text


def test_deploy_workflow_runs_on_main_push_and_manual_dispatch():
    deploy_text = DEPLOY_YML.read_text(encoding="utf-8")

    assert "push:" in deploy_text
    assert "branches: [main]" in deploy_text
    assert "workflow_dispatch:" in deploy_text
