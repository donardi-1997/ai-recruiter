"""Contracts for bootstrapping AI Recruiter in the current AWS account."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGETS = (
    ROOT / ".github" / "workflows" / "deploy.yml",
    ROOT / "scripts" / "deploy-api.sh",
    ROOT / "scripts" / "deploy-worker.sh",
    ROOT / "app" / "infrastructure" / "bedrock" / "config.py",
    ROOT / "app" / "infrastructure" / "imports" / "ingestion.py",
    ROOT / "app" / "infrastructure" / "imports" / "storage.py",
)


def _combined() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in TARGETS)


def test_previous_aws_account_and_generated_resource_ids_are_not_embedded():
    content = _combined()
    for stale in (
        "765761474007",
        "VUGNMJQAEN",
        "P8SUL2VFHA",
        "ai-cv-rag-adrian-2026",
        "E1IBIX4EWENEP7",
    ):
        assert stale not in content


def test_deploy_targets_current_account_via_github_oidc_role():
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )
    assert "AiRecruiterGithubDeployRole" in workflow
    assert "890876258895" in workflow
    assert "aws-actions/configure-aws-credentials" in workflow


def test_lightsail_ssh_uses_temporary_access_details_not_persistent_private_key_secret():
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )
    assert "get-instance-access-details" in workflow
    assert "--protocol ssh" in workflow
    assert "LIGHTSAIL_SSH_KEY_SECRET" not in workflow
    assert "/ai-recruiter/prod/lightsail-ssh-key" not in workflow


def test_lightsail_bootstrap_generates_runtime_identity_on_host_and_registers_only_public_ca():
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )
    assert "Bootstrap Lightsail runtime identity" in workflow
    assert "openssl req -x509" in workflow
    assert "client.key" in workflow
    assert "scp" in workflow
    assert "ca.crt" in workflow
    assert "rolesanywhere create-trust-anchor" in workflow
    assert "aws_signing_helper" in workflow
    assert "credential_process" in workflow
    assert "scp" in workflow and "client.key ubuntu@" not in workflow


def test_api_and_worker_require_runtime_resource_environment():
    for filename in ("deploy-api.sh", "deploy-worker.sh"):
        content = (ROOT / "scripts" / filename).read_text(encoding="utf-8")
        for key in (
            "AWS_ACCOUNT_ID",
            "S3_BUCKET",
            "KNOWLEDGE_BASE_ID",
            "DATA_SOURCE_ID",
            "COGNITO_USER_POOL_ID",
            "COGNITO_CLIENT_ID",
        ):
            assert key in content


def test_bedrock_and_canonical_storage_have_no_stale_resource_defaults():
    config = (ROOT / "app" / "infrastructure" / "bedrock" / "config.py").read_text(
        encoding="utf-8"
    )
    ingestion = (
        ROOT / "app" / "infrastructure" / "imports" / "ingestion.py"
    ).read_text(encoding="utf-8")
    storage = (ROOT / "app" / "infrastructure" / "imports" / "storage.py").read_text(
        encoding="utf-8"
    )

    assert 'os.getenv("KNOWLEDGE_BASE_ID", "")' in config
    assert 'os.getenv("KNOWLEDGE_BASE_ID", "")' in ingestion
    assert 'os.getenv("DATA_SOURCE_ID", "")' in ingestion
    assert 'os.getenv("S3_BUCKET", "")' in storage
