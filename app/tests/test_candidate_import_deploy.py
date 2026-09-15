"""Deployment contracts for the candidate-import API/worker production slice."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"
API_SCRIPT = ROOT / "scripts" / "deploy-api.sh"
WORKER_SCRIPT = ROOT / "scripts" / "deploy-worker.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_worker_deploy_uses_same_immutable_backend_image_and_command():
    worker = _read(WORKER_SCRIPT)
    assert 'ECR_REPO="ai-recruiter-api"' in worker
    assert 'ECR_TAG="${ECR_TAG:-latest}"' in worker
    assert 'CONTAINER_NAME="ai-recruiter-worker"' in worker
    assert "--restart unless-stopped" in worker
    assert "python -m app.workers.candidate_imports" in worker
    assert 'docker inspect "$CONTAINER_NAME"' in worker
    assert 'OLD_WORKER_IMAGE' in worker


def test_api_and_worker_receive_candidate_import_environment():
    api = _read(API_SCRIPT)
    worker = _read(WORKER_SCRIPT)
    for content in (api, worker):
        assert "IMPORT_STAGING_BUCKET" in content
        assert "IMPORT_QUEUE_URL" in content
        assert "IMPORT_EVALUATION_CONCURRENCY" in content


def test_worker_preserves_roles_anywhere_mounts_and_runtime_role_checks():
    worker = _read(WORKER_SCRIPT)
    for destination in (
        "/root/.aws/config",
        "/usr/local/bin/aws_signing_helper",
        "/run/rolesanywhere/client.crt",
        "/run/rolesanywhere/client.key",
    ):
        assert destination in worker
    assert "AiRecruiterBedrockRuntimeRole" in worker
    assert "765761474007" in worker


def test_workflow_provisions_import_infrastructure_before_migration_and_deploy():
    workflow = _read(WORKFLOW)
    markers = [
        "aws cloudformation deploy",
        "python -m app.scripts.migrate_candidate_import",
        "python -m app.scripts.backfill_candidate_identities",
        "ai-recruiter-deploy-api.sh",
        "ai-recruiter-deploy-worker.sh",
        "Deploy Frontend",
    ]
    positions = [workflow.index(marker) for marker in markers]
    assert positions == sorted(positions)


def test_workflow_reads_stack_outputs_and_passes_them_to_runtime():
    workflow = _read(WORKFLOW)
    assert "ai-recruiter-candidate-import" in workflow
    assert "RuntimeRoleArn" in workflow
    assert "ImportStagingBucket" in workflow
    assert "ImportQueueUrl" in workflow
    assert "IMPORT_STAGING_BUCKET" in workflow
    assert "IMPORT_QUEUE_URL" in workflow


def test_workflow_copies_and_runs_worker_deploy_script_with_sha_tag():
    workflow = _read(WORKFLOW)
    assert "scripts/deploy-worker.sh" in workflow
    assert "/tmp/ai-recruiter-deploy-worker.sh" in workflow
    assert 'ECR_TAG="${{ github.sha }}"' in workflow
    assert "github.event_name != 'pull_request'" in workflow


def test_migration_and_backfill_run_before_existing_api_is_replaced():
    workflow = _read(WORKFLOW)
    migrate = workflow.index("python -m app.scripts.migrate_candidate_import")
    backfill = workflow.index("python -m app.scripts.backfill_candidate_identities")
    api_deploy = workflow.index("/tmp/ai-recruiter-deploy-api.sh")
    assert migrate < backfill < api_deploy


def test_workflow_does_not_inline_worker_docker_run():
    workflow = _read(WORKFLOW)
    for line in workflow.splitlines():
        if "docker run" in line and "ai-recruiter-worker" in line:
            raise AssertionError("worker creation must stay in deploy-worker.sh")
