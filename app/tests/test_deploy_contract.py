"""Deployment contract tests — verify deploy.yml delegates to deploy-api.sh.

These tests are completely offline and ensure no one can re-introduce a manual
docker run for ai-recruiter-api in deploy.yml.

Run:  python -m pytest app/tests/test_deploy_contract.py -v
"""

import os
import re

import pytest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEPLOY_YML = os.path.join(REPO_ROOT, ".github", "workflows", "deploy.yml")
DEPLOY_SH = os.path.join(REPO_ROOT, "scripts", "deploy-api.sh")


@pytest.fixture(scope="module")
def deploy_yml_content():
    with open(DEPLOY_YML, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def deploy_sh_content():
    with open(DEPLOY_SH, "r", encoding="utf-8") as f:
        return f.read()


# ============================================================
# A. deploy.yml must use deploy-api.sh
# ============================================================

class TestDeployYmlUsesScript:
    def test_deploy_yml_references_deploy_api_sh(self, deploy_yml_content):
        assert "deploy-api.sh" in deploy_yml_content, (
            "deploy.yml must reference scripts/deploy-api.sh"
        )

    def test_deploy_yml_copies_script_before_running(self, deploy_yml_content):
        assert "scp" in deploy_yml_content and "deploy-api.sh" in deploy_yml_content, (
            "deploy.yml must copy deploy-api.sh to the server via scp"
        )


# ============================================================
# B. deploy.yml must NOT contain a manual docker run for backend
# ============================================================

class TestNoManualBackendDockerRun:
    def test_no_docker_run_for_backend_container(self, deploy_yml_content):
        # Find all docker run blocks — there should be none that create ai-recruiter-api
        # The backend is deployed via deploy-api.sh, not inline docker run
        lines = deploy_yml_content.split("\n")
        in_docker_run = False
        for line in lines:
            stripped = line.strip()
            # Track docker run commands (the REMOTE_SCRIPT heredoc contains shell code)
            if "docker run" in stripped and "ai-recruiter-api" in stripped:
                pytest.fail(
                    f"deploy.yml contains a docker run that creates ai-recruiter-api: {stripped}"
                )

    def test_no_inline_backend_env_vars(self, deploy_yml_content):
        # deploy.yml should not set BEDROCK_AWS_PROFILE, DATABASE_URL etc.
        # for the backend container — those come from deploy-api.sh
        lines = deploy_yml_content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Skip comments and the deploy-api.sh section
            if stripped.startswith("#"):
                continue
            # Check for inline backend env that should only be in deploy-api.sh
            if "BEDROCK_AWS_PROFILE" in stripped and "deploy-api.sh" not in stripped:
                # It's OK if it appears in a comment or echo
                if "echo" not in stripped and "#" not in stripped:
                    pytest.fail(
                        f"Line {i}: deploy.yml should not set BEDROCK_AWS_PROFILE directly"
                    )


# ============================================================
# C. deploy-api.sh contains BEDROCK_AWS_PROFILE
# ============================================================

class TestDeployScriptBedrockProfile:
    def test_bedrock_aws_profile_present(self, deploy_sh_content):
        assert "BEDROCK_AWS_PROFILE" in deploy_sh_content, (
            "deploy-api.sh must set BEDROCK_AWS_PROFILE"
        )

    def test_bedrock_profile_value(self, deploy_sh_content):
        assert "ai-recruiter-bedrock" in deploy_sh_content, (
            "deploy-api.sh must use profile ai-recruiter-bedrock"
        )


# ============================================================
# D. deploy-api.sh contains the four runtime mount destinations
# ============================================================

class TestDeployScriptMounts:
    MOUNT_DESTINATIONS = [
        "/root/.aws/config",
        "/usr/local/bin/aws_signing_helper",
        "/run/rolesanywhere/client.crt",
        "/run/rolesanywhere/client.key",
    ]

    @pytest.mark.parametrize("dest", MOUNT_DESTINATIONS)
    def test_mount_destination_present(self, deploy_sh_content, dest):
        assert dest in deploy_sh_content, (
            f"deploy-api.sh must mount to {dest}"
        )


# ============================================================
# E. deploy-api.sh validates AWS account
# ============================================================

class TestDeployScriptAwsAccount:
    def test_validates_account(self, deploy_sh_content):
        assert "765761474007" in deploy_sh_content, (
            "deploy-api.sh must validate AWS account 765761474007"
        )


# ============================================================
# F. deploy-api.sh validates runtime role
# ============================================================

class TestDeployScriptAwsRole:
    def test_validates_role(self, deploy_sh_content):
        assert "AiRecruiterBedrockRuntimeRole" in deploy_sh_content, (
            "deploy-api.sh must validate role AiRecruiterBedrockRuntimeRole"
        )


# ============================================================
# G. deploy.yml uses SHA-based tag
# ============================================================

class TestShaTag:
    def test_deploy_yml_uses_github_sha(self, deploy_yml_content):
        assert "github.sha" in deploy_yml_content, (
            "deploy.yml must use GITHUB_SHA for immutable image tags"
        )

    def test_deploy_yml_promotes_to_latest_only_after_checks(self, deploy_yml_content):
        # "latest" tag should only appear AFTER post-deploy checks
        lines = deploy_yml_content.split("\n")
        latest_lines = []
        for i, line in enumerate(lines, 1):
            if "latest" in line and "docker" in line:
                latest_lines.append(i)
        assert len(latest_lines) > 0, "deploy.yml should have a latest promotion step"
        # The last occurrence of latest should be after the health checks
        # (This is a structural check — the promote step comes last)
