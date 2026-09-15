from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/nano-diagnostics.yml"


def test_nano_diagnostics_workflow_is_read_only_and_reusable():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "free -m" in workflow
    assert "swapon --show" in workflow
    assert "docker stats --no-stream" in workflow
    assert "docker system df" in workflow
    assert "SHOW shared_buffers" in workflow
    assert "SHOW work_mem" in workflow
    assert "SHOW maintenance_work_mem" in workflow
    assert "SHOW effective_cache_size" in workflow
    assert "SHOW max_connections" in workflow

    forbidden = (
        "docker stop ",
        "docker rm ",
        "docker image prune",
        "docker container prune",
        "docker builder prune",
        "systemctl restart",
        "systemctl stop",
        "apt install",
        "apt-get install",
        "swapoff",
        "fallocate",
        "mkswap",
        "sed -i",
    )
    for token in forbidden:
        assert token not in workflow
