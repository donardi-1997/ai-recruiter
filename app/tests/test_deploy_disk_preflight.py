"""Regression contract for Docker disk cleanup before production image pulls."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_production_preflight_reclaims_unused_docker_disk_before_pull():
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    migrate = workflow.index("- name: Migrate and backfill production database")
    deploy = workflow.index("- name: Deploy API worker and frontend via SSH", migrate)
    preflight = workflow[migrate:deploy]

    cleanup = preflight.index("docker image prune -a -f")
    pull = preflight.index('docker pull "$ECR_REGISTRY/$ECR_BACKEND_REPO:${{ github.sha }}"')

    assert cleanup < pull
    assert "docker container prune -f" in preflight
    assert "docker builder prune -a -f" in preflight
    assert "docker system df" in preflight
    assert "--volumes" not in preflight
