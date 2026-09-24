"""Deployment contracts for managed training media."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"
API_SCRIPT = ROOT / "scripts" / "deploy-api.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_workflow_provisions_training_bucket_before_api_deploy():
    workflow = _read(WORKFLOW)
    provision = workflow.index("ai-recruiter-training-content")
    api_deploy = workflow.index("/tmp/ai-recruiter-deploy-api.sh")
    assert provision < api_deploy
    assert "infra/training-content.yml" in workflow
    assert "TrainingContentBucket" in workflow


def test_workflow_passes_training_bucket_to_api_runtime():
    workflow = _read(WORKFLOW)
    api_script = _read(API_SCRIPT)

    assert 'TRAINING_CONTENT_BUCKET="$TRAINING_CONTENT_BUCKET"' in workflow
    assert 'TRAINING_CONTENT_BUCKET="${TRAINING_CONTENT_BUCKET:?TRAINING_CONTENT_BUCKET is required}"' in api_script
    assert '-e "TRAINING_CONTENT_BUCKET=$TRAINING_CONTENT_BUCKET"' in api_script
    assert '"TRAINING_CONTENT_BUCKET=$TRAINING_CONTENT_BUCKET"' in api_script
