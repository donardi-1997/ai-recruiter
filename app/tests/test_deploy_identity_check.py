from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_api_deploy_identity_check_uses_canonical_bedrock_session():
    script = (ROOT / "scripts/deploy-api.sh").read_text(encoding="utf-8")

    assert "from app.infrastructure.bedrock.session import get_cached_session" in script
    assert "s = get_cached_session()" in script
    assert "from app import evaluation" not in script
    assert "evaluation._bedrock_session" not in script
