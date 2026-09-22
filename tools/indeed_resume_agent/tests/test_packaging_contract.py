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


def test_build_is_onedir_and_packages_browser_use_cdp_runtime():
    text=read("build.ps1")
    lower=text.lower()
    assert "--onedir" in lower
    assert "--onefile" not in lower
    assert "browser_use.browser" in text
    assert "cdp_use" in text
    assert "browser_harness" in text
    assert "--paths" in lower
    assert "playwright install chromium" not in lower

    requirements = read("requirements.txt")
    assert 'browser-use==0.13.10' in requirements

    main = read("main.py")
    assert "IndeedBrowserUse" in main
    assert "browser = IndeedBrowserUse(config)" in main


def test_browser_use_driver_is_deterministic_and_has_no_llm_agent():
    text=read("browser_use_driver.py")
    assert "get_or_create_cdp_session" in text
    assert "Network.getResponseBody" in text
    assert "_INDEED_RESUME_DOWNLOAD_PATH" in text
    assert "Agent(" not in text
    assert "ChatBrowserUse" not in text


def test_readme_documents_chrome_credential_setup_and_single_task_cutover():
    text=read("README.md")
    assert "Google Chrome" in text
    assert "browser-profile-chrome" in text
    assert "Windows Credential Manager" in text
    assert "Open Indeed" in text
    assert "Browser Use" in text
    assert "una sola" in text.lower() or "un solo" in text.lower()


def test_production_ui_starts_paused_before_agent_thread():
    text = read("ui.py")
    pause_at = text.index("worker.pause()", text.index("def run_ui"))
    thread_at = text.index("threading.Thread", text.index("def run_ui"))
    assert pause_at < thread_at
    assert "mantén Chrome abierto y luego pulsa Resume" in text
