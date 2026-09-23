from tools.indeed_resume_agent.browser_use_driver import IndeedBrowserUse
from tools.indeed_resume_agent.config import AgentConfig
from tools.indeed_resume_agent.download_capture_compat import (
    install_download_capture_compat,
)


def _config(tmp_path):
    return AgentConfig(
        api_base_url="https://example.com",
        browser_profile_dir=tmp_path / "profile",
        request_timeout_seconds=1.0,
    )


def _alternate_attachment_event():
    return {
        "requestId": "resume-alt-1",
        "response": {
            "url": "https://files.indeed.com/download/opaque-id",
            "status": 200,
            "mimeType": "application/octet-stream",
            "headers": {
                "content-type": "application/octet-stream",
                "content-disposition": 'attachment; filename="Natalia-Duran-CV.pdf"',
            },
        },
    }


def test_alternate_attachment_endpoint_is_captured_as_resume(tmp_path):
    driver = IndeedBrowserUse(
        _config(tmp_path),
        browser_session_class=object,
        browser_executable_resolver=lambda: "chrome.exe",
    )
    try:
        install_download_capture_compat(driver)
        driver._download_future = driver._loop.create_future()
        driver._on_response_received(_alternate_attachment_event(), "session-1")

        assert "resume-alt-1" in driver._resume_response_meta
    finally:
        driver.close()


def test_alternate_attachment_is_ignored_when_no_resume_download_is_armed(tmp_path):
    driver = IndeedBrowserUse(
        _config(tmp_path),
        browser_session_class=object,
        browser_executable_resolver=lambda: "chrome.exe",
    )
    try:
        install_download_capture_compat(driver)
        driver._on_response_received(_alternate_attachment_event(), "session-1")

        assert driver._resume_response_meta == {}
    finally:
        driver.close()
