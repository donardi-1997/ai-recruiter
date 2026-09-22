import sys

import pytest

from tools.indeed_resume_agent.self_test import run_self_test


pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Real Browser Use/Chrome/Windows Credential Manager preflight only runs on Windows.",
)


def test_real_windows_browser_use_chrome_and_credential_manager():
    assert run_self_test() == 0
