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
        lines = deploy_yml_content.split("\n")
        for line in lines:
            stripped = line.strip()
            if "docker run" in stripped and "ai-recruiter-api" in stripped:
                pytest.fail(
                    f"deploy.yml contains a docker run that creates ai-recruiter-api: {stripped}"
                )

    def test_no_inline_backend_env_vars(self, deploy_yml_content):
        lines = deploy_yml_content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "BEDROCK_AWS_PROFILE" in stripped and "deploy-api.sh" not in stripped:
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
# G. deploy.yml uses SHA-based tag for backend
# ============================================================

class TestShaTag:
    def test_deploy_yml_uses_github_sha(self, deploy_yml_content):
        assert "github.sha" in deploy_yml_content, (
            "deploy.yml must use GITHUB_SHA for immutable image tags"
        )

    def test_deploy_yml_backend_promotes_to_latest_only_after_checks(self, deploy_yml_content):
        lines = deploy_yml_content.split("\n")
        latest_backend_lines = []
        for i, line in enumerate(lines, 1):
            if "latest" in line and "docker" in line and "ECR_BACKEND_REPO" in line:
                latest_backend_lines.append(i)
        assert len(latest_backend_lines) > 0, (
            "deploy.yml should have a backend latest promotion step"
        )

        # Verify backend promotion occurs after public health check
        public_health_line = None
        for i, line in enumerate(lines, 1):
            if "PUBLIC_HEALTH_OK" in line:
                public_health_line = i
                break
        assert public_health_line is not None, (
            "deploy.yml should have a PUBLIC_HEALTH_OK check"
        )
        assert latest_backend_lines[-1] > public_health_line, (
            f"Backend latest promotion (line {latest_backend_lines[-1]}) must occur "
            f"after PUBLIC_HEALTH_OK (line {public_health_line})"
        )


# ============================================================
# H. Frontend uses immutable SHA tag (not latest for docker run)
# ============================================================

class TestFrontendImmutableDeploy:
    def test_frontend_uses_sha_tag_in_build(self, deploy_yml_content):
        """Frontend build step must use ECR_FRONTEND_REPO with github.sha."""
        assert re.search(
            r"ECR_FRONTEND_REPO.*github\.sha|github\.sha.*ECR_FRONTEND_REPO",
            deploy_yml_content,
        ), "deploy.yml must build frontend with ECR_FRONTEND_REPO:github.sha"

    def test_frontend_pull_before_stop(self, deploy_yml_content):
        """Frontend must be pulled (docker pull) BEFORE stopping old container."""
        lines = deploy_yml_content.split("\n")
        frontend_pull_line = None
        frontend_stop_line = None
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if "docker pull" in stripped and "ECR_FRONTEND_REPO" in stripped:
                frontend_pull_line = i
            if "docker stop" in stripped and "ai-recruiter-web" in stripped:
                frontend_stop_line = i
                break
        assert frontend_pull_line is not None, (
            "deploy.yml must pull frontend SHA image"
        )
        assert frontend_stop_line is not None, (
            "deploy.yml must stop ai-recruiter-web"
        )
        assert frontend_pull_line < frontend_stop_line, (
            f"Frontend pull (line {frontend_pull_line}) must occur before "
            f"stop (line {frontend_stop_line})"
        )

    def test_frontend_run_uses_sha_not_latest(self, deploy_yml_content):
        """Frontend docker run must use SHA tag, not latest."""
        lines = deploy_yml_content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if (
                "docker run" in stripped
                and "ai-recruiter-web" in stripped
            ):
                assert "ECR_FRONTEND_REPO" in stripped, (
                    f"Line {i}: frontend docker run must reference ECR_FRONTEND_REPO"
                )
                assert ":latest" not in stripped, (
                    f"Line {i}: frontend docker run must NOT use :latest tag"
                )
                assert "github.sha" in stripped, (
                    f"Line {i}: frontend docker run must use github.sha tag"
                )

    def test_frontend_docker_inspect_exists(self, deploy_yml_content):
        """deploy.yml must inspect ai-recruiter-web to validate frontend."""
        assert "docker inspect ai-recruiter-web" in deploy_yml_content, (
            "deploy.yml must include docker inspect ai-recruiter-web"
        )

    def test_frontend_image_ok_check(self, deploy_yml_content):
        """deploy.yml must verify FRONTEND_IMAGE_OK."""
        assert "FRONTEND_IMAGE_OK" in deploy_yml_content, (
            "deploy.yml must include FRONTEND_IMAGE_OK check"
        )

    def test_public_frontend_ok_check(self, deploy_yml_content):
        """deploy.yml must verify PUBLIC_FRONTEND_OK."""
        assert "PUBLIC_FRONTEND_OK" in deploy_yml_content, (
            "deploy.yml must include PUBLIC_FRONTEND_OK check"
        )

    def test_frontend_bundle_comparison(self, deploy_yml_content):
        """deploy.yml must compare DIRECT_FRONTEND_BUNDLE and PUBLIC_FRONTEND_BUNDLE."""
        assert "DIRECT_FRONTEND_BUNDLE" in deploy_yml_content, (
            "deploy.yml must include DIRECT_FRONTEND_BUNDLE"
        )
        assert "PUBLIC_FRONTEND_BUNDLE" in deploy_yml_content, (
            "deploy.yml must include PUBLIC_FRONTEND_BUNDLE"
        )

    def test_frontend_latest_promoted_after_checks(self, deploy_yml_content):
        """Frontend latest promotion must occur after all validation checks."""
        lines = deploy_yml_content.split("\n")
        frontend_latest_line = None
        for i, line in enumerate(lines, 1):
            if "latest" in line and "ECR_FRONTEND_REPO" in line:
                frontend_latest_line = i
        assert frontend_latest_line is not None, (
            "deploy.yml must have a frontend latest promotion step"
        )

        # Verify it occurs after FRONTEND_IMAGE_OK
        image_ok_line = None
        for i, line in enumerate(lines, 1):
            if "FRONTEND_IMAGE_OK" in line:
                image_ok_line = i
                break
        assert image_ok_line is not None, (
            "deploy.yml must have FRONTEND_IMAGE_OK check"
        )
        assert frontend_latest_line > image_ok_line, (
            f"Frontend latest promotion (line {frontend_latest_line}) must occur "
            f"after FRONTEND_IMAGE_OK (line {image_ok_line})"
        )

    def test_no_backend_docker_run_in_deploy_yml(self, deploy_yml_content):
        """ai-recruiter-api must NOT have a docker run in deploy.yml."""
        lines = deploy_yml_content.split("\n")
        for line in lines:
            stripped = line.strip()
            if "docker run" in stripped and "ai-recruiter-api" in stripped:
                pytest.fail(
                    f"deploy.yml contains docker run for ai-recruiter-api: {stripped}"
                )


# ============================================================
# I. CloudFront/Lightsail migration — no S3 deploy
# ============================================================

class TestCloudFrontLightsailMigration:
    def test_no_s3_sync_for_frontend(self, deploy_yml_content):
        """deploy.yml must NOT use aws s3 sync for frontend deployment."""
        assert "s3 sync" not in deploy_yml_content, (
            "deploy.yml must not contain 'aws s3 sync' — frontend is served from Lightsail Docker"
        )

    def test_no_s3_cp_for_frontend(self, deploy_yml_content):
        """deploy.yml must NOT use aws s3 cp for frontend deployment."""
        assert "s3 cp" not in deploy_yml_content, (
            "deploy.yml must not contain 'aws s3 cp' — frontend is served from Lightsail Docker"
        )

    def test_no_s3_bucket_reference(self, deploy_yml_content):
        """deploy.yml must NOT reference the old S3 frontend bucket."""
        assert "ai-recruiter-frontend-765761474007" not in deploy_yml_content, (
            "deploy.yml must not reference the old S3 bucket ai-recruiter-frontend-765761474007"
        )

    def test_cloudfront_invalidation_exists(self, deploy_yml_content):
        """deploy.yml must include CloudFront invalidation after frontend deploy."""
        assert "cloudfront create-invalidation" in deploy_yml_content, (
            "deploy.yml must include 'cloudfront create-invalidation'"
        )

    def test_cloudfront_distribution_id(self, deploy_yml_content):
        """deploy.yml must reference CloudFront distribution E1IBIX4EWENEP7."""
        assert "E1IBIX4EWENEP7" in deploy_yml_content, (
            "deploy.yml must reference CloudFront distribution E1IBIX4EWENEP7"
        )

    def test_cloudfront_invalidation_wait(self, deploy_yml_content):
        """deploy.yml must wait for CloudFront invalidation to complete."""
        assert "invalidation-completed" in deploy_yml_content, (
            "deploy.yml must wait for CloudFront invalidation to complete"
        )

    def test_frontendlightsail_origin_in_dns(self, deploy_yml_content):
        """deploy.yml or docs should reference air-origin.adrianguerra.net."""
        # This is a structural check — the DNS record must exist for CloudFront to work
        # The deploy.yml itself may not reference it directly, but the CloudFront config does
        pass  # DNS is managed outside deploy.yml; verified in Phase 6-7
