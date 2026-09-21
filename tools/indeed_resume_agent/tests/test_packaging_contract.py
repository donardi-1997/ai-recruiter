from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AGENT = ROOT / "tools" / "indeed_resume_agent"


def read(name):
    return (AGENT / name).read_text(encoding="utf-8")


def test_install_uses_dedicated_venv_agent_requirements_and_hidden_token_prompt():
    text=read("install.ps1")
    lower=text.lower()
    assert "python -m venv .agent-venv" in lower
    assert "tools\\indeed_resume_agent\\requirements.txt" in lower
    assert "tools.indeed_resume_agent.setup_token" in text
    assert "X-ASIATI-Agent-Token" not in text
    assert "agent-token=" not in lower


def test_run_launches_module_from_repo_root():
    text=read("run.ps1")
    assert "tools.indeed_resume_agent.main" in text
    assert "Set-Location" in text


def test_build_is_onedir_collects_playwright_and_does_not_install_chromium():
    text=read("build.ps1")
    lower=text.lower()
    assert "--onedir" in lower
    assert "--onefile" not in lower
    assert "--collect-all" in lower and "playwright" in lower
    assert "--paths" in lower
    assert "playwright install chromium" not in lower
    browser = read("browser.py")
    assert 'self._playwright_channel = "chrome"' in browser
    assert 'channel=self._playwright_channel' in browser


def test_readme_documents_chrome_credential_setup_and_single_task_cutover():
    text=read("README.md")
    assert "Google Chrome" in text
    assert "browser-profile-chrome" in text
    assert "Windows Credential Manager" in text
    assert "Open Indeed" in text
    assert "una sola" in text.lower() or "un solo" in text.lower()
