"""Offline contracts for the production deployment boundary."""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"
API_SCRIPT = ROOT / "scripts" / "deploy-api.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def deploy_yml_content():
    return _read(WORKFLOW)


@pytest.fixture(scope="module")
def deploy_sh_content():
    return _read(API_SCRIPT)


def test_deploy_yml_delegates_backend_creation_to_script(deploy_yml_content):
    assert "scripts/deploy-api.sh" in deploy_yml_content
    assert "scp" in deploy_yml_content
    for line in deploy_yml_content.splitlines():
        if "docker run" in line and "ai-recruiter-api" in line:
            pytest.fail("backend container creation must stay in deploy-api.sh")


def test_deploy_script_keeps_roles_anywhere_profile_and_mounts(deploy_sh_content):
    assert "BEDROCK_AWS_PROFILE" in deploy_sh_content
    assert "ai-recruiter-bedrock" in deploy_sh_content
    for destination in (
        "/root/.aws/config",
        "/usr/local/bin/aws_signing_helper",
        "/run/rolesanywhere/client.crt",
        "/run/rolesanywhere/client.key",
    ):
        assert destination in deploy_sh_content


def test_deploy_script_validates_dynamic_account_and_runtime_role(deploy_sh_content):
    assert 'AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:?AWS_ACCOUNT_ID is required}"' in deploy_sh_content
    assert 'EXPECTED_AWS_ACCOUNT="${EXPECTED_AWS_ACCOUNT:-$AWS_ACCOUNT_ID}"' in deploy_sh_content
    assert "AiRecruiterBedrockRuntimeRole" in deploy_sh_content
    assert "765761474007" not in deploy_sh_content


def test_workflow_uses_current_account_github_oidc_role(deploy_yml_content):
    assert "aws-actions/configure-aws-credentials@v5" in deploy_yml_content
    assert "arn:aws:iam::890876258895:role/AiRecruiterGithubDeployRole" in deploy_yml_content
    assert 'AWS_ACCOUNT_ID: "890876258895"' in deploy_yml_content
    assert "aws sts get-caller-identity" in deploy_yml_content


def test_backend_uses_immutable_sha_then_promotes_after_health(deploy_yml_content):
    assert "ECR_BACKEND_REPO:${{ github.sha }}" in deploy_yml_content
    lines = deploy_yml_content.splitlines()
    health = next(i for i, line in enumerate(lines) if "PUBLIC_HEALTH_OK" in line)
    latest = max(
        i
        for i, line in enumerate(lines)
        if "latest" in line and "ECR_BACKEND_REPO" in line and "docker" in line
    )
    assert latest > health


def test_frontend_pull_precedes_stop_and_sha_is_verified(deploy_yml_content):
    lines = deploy_yml_content.splitlines()
    pull = next(
        i for i, line in enumerate(lines)
        if "docker pull" in line and "ECR_FRONTEND_REPO" in line
    )
    stop = next(
        i for i, line in enumerate(lines)
        if "docker stop" in line and "ai-recruiter-web" in line
    )
    assert pull < stop
    assert "docker inspect ai-recruiter-web" in deploy_yml_content
    assert "FRONTEND_IMAGE_OK" in deploy_yml_content
    assert "PUBLIC_FRONTEND_OK" in deploy_yml_content
    assert "DIRECT_FRONTEND_BUNDLE" in deploy_yml_content
    assert "PUBLIC_FRONTEND_BUNDLE" in deploy_yml_content


def test_frontend_latest_is_promoted_only_after_runtime_check(deploy_yml_content):
    lines = deploy_yml_content.splitlines()
    image_ok = next(i for i, line in enumerate(lines) if "FRONTEND_IMAGE_OK" in line)
    latest = max(
        i
        for i, line in enumerate(lines)
        if "latest" in line and "ECR_FRONTEND_REPO" in line
    )
    assert latest > image_ok


def test_frontend_is_not_deployed_to_s3(deploy_yml_content):
    assert "s3 sync" not in deploy_yml_content
    assert "s3 cp" not in deploy_yml_content


def test_deploy_has_no_cloudfront_dependency(deploy_yml_content):
    assert "CLOUDFRONT_DISTRIBUTION_ID" not in deploy_yml_content
    assert "cloudfront create-invalidation" not in deploy_yml_content
    assert "us-east-1" not in deploy_yml_content


def test_runtime_resource_configuration_comes_from_aws_secret(deploy_yml_content):
    assert "/ai-recruiter/prod/runtime-config" in deploy_yml_content
    assert "secretsmanager get-secret-value" in deploy_yml_content
    for key in (
        "S3_BUCKET",
        "KNOWLEDGE_BASE_ID",
        "DATA_SOURCE_ID",
        "COGNITO_USER_POOL_ID",
        "COGNITO_CLIENT_ID",
    ):
        assert key in deploy_yml_content
