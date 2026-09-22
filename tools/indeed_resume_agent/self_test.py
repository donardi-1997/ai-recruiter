from __future__ import annotations

import os
import tempfile
from pathlib import Path


_SELF_TEST_SERVICE = "ASIATI Resume Agent Self Test"
_SELF_TEST_USERNAME = "qa-preflight"


def run_self_test() -> int:
    """Validate packaged Windows integrations without contacting production."""
    token = f"self-test-{os.getpid()}-" + ("x" * 40)
    keyring = None

    try:
        import keyring as loaded_keyring

        keyring = loaded_keyring
        keyring.set_password(_SELF_TEST_SERVICE, _SELF_TEST_USERNAME, token)
        if keyring.get_password(_SELF_TEST_SERVICE, _SELF_TEST_USERNAME) != token:
            return 21

        from playwright.sync_api import sync_playwright
        from tools.indeed_resume_agent.browser import _resolve_browser_executable

        chrome = Path(_resolve_browser_executable("chrome"))
        if not chrome.is_file():
            return 31

        with tempfile.TemporaryDirectory(prefix="asiati-resume-agent-self-test-") as temp:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(Path(temp) / "chrome-profile"),
                    channel="chrome",
                    headless=True,
                    accept_downloads=True,
                    chromium_sandbox=True,
                )
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    page.set_content(
                        "<title>ASIATI packaged preflight</title>"
                        "<body>resume-agent-ok</body>"
                    )
                    if page.title() != "ASIATI packaged preflight":
                        return 41
                    if page.locator("body").inner_text() != "resume-agent-ok":
                        return 42
                finally:
                    context.close()
        return 0
    except Exception:
        return 1
    finally:
        if keyring is not None:
            try:
                keyring.delete_password(_SELF_TEST_SERVICE, _SELF_TEST_USERNAME)
            except Exception:
                pass
