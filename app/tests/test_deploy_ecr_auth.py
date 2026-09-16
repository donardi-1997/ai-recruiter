from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _script(name: str) -> str:
    return (REPO_ROOT / "scripts" / name).read_text()


def test_api_deploy_authenticates_to_ecr_before_pull():
    content = _script("deploy-api.sh")
    login = 'aws ecr get-login-password --region "$AWS_REGION" --profile "$BEDROCK_PROFILE"'
    docker_login = 'docker login --username AWS --password-stdin'
    assert login in content
    assert docker_login in content
    assert content.index(login) < content.index('docker pull "$ECR_IMAGE"')


def test_worker_deploy_authenticates_to_ecr_before_pull():
    content = _script("deploy-worker.sh")
    login = 'aws ecr get-login-password --region "$AWS_REGION" --profile "$BEDROCK_PROFILE"'
    docker_login = 'docker login --username AWS --password-stdin'
    assert login in content
    assert docker_login in content
    assert content.index(login) < content.index('docker pull "$ECR_IMAGE"')
