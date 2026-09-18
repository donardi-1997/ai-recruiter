from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "indeed-resume-agent.yml"


def test_agent_workflow_runs_unit_and_server_contract_tests():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "tools/indeed_resume_agent/tests" in text
    assert "app/tests/test_indeed_agent_auth.py" in text
    assert "app/tests/test_indeed_agent_routes.py" in text
    assert "app/tests/test_indeed_agent_upload.py" in text
    assert "app/tests/test_indeed_email_resume_leases.py" in text


def test_agent_workflow_builds_windows_onedir_and_uploads_artifact():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "runs-on: windows-latest" in text
    assert "tools\\indeed_resume_agent\\build.ps1" in text
    assert "actions/upload-artifact@v4" in text
    assert "ASIATI-Resume-Agent-Windows" in text
