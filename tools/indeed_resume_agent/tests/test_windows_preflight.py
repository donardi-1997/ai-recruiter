import sys
from pathlib import Path

import pytest

from tools.indeed_resume_agent.browser import _resolve_browser_executable
from tools.indeed_resume_agent.credential_store import (
    delete_agent_token,
    read_agent_token,
    write_agent_token,
)


pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Real Chrome/Windows Credential Manager preflight only runs on Windows.",
)


def test_real_windows_chrome_channel_and_credential_manager(tmp_path):
    """Exercise the two Windows integrations that Linux CI cannot validate."""
    chrome = Path(_resolve_browser_executable("chrome"))
    assert chrome.is_file()

    from playwright.sync_api import sync_playwright

    profile = tmp_path / "chrome-profile"
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            channel="chrome",
            headless=True,
            accept_downloads=True,
            chromium_sandbox=True,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_content("<title>ASIATI preflight</title><body>ok</body>")
            assert page.title() == "ASIATI preflight"
            assert page.locator("body").inner_text() == "ok"
        finally:
            context.close()

    token = "windows-preflight-" + ("x" * 40)
    try:
        write_agent_token(token)
        assert read_agent_token() == token
    finally:
        try:
            delete_agent_token()
        except Exception:
            pass
