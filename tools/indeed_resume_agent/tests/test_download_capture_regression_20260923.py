from tools.indeed_resume_agent.browser_use_driver import IndeedBrowserUse
from tools.indeed_resume_agent.config import AgentConfig


def _config(tmp_path):
    return AgentConfig(
        api_base_url="https://example.com",
        browser_profile_dir=tmp_path / "profile",
        request_timeout_seconds=1.0,
    )


def test_alternate_attachment_endpoint_is_captured_as_resume(tmp_path):
    driver = IndeedBrowserUse(
        _config(tmp_path),
        browser_session_class=object,
        browser_executable_resolver=lambda: "chrome.exe",
    )
    try:
        driver._download_future = driver._loop.create_future()
        driver._on_response_received(
            {
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
            },
            "session-1",
        )

        assert "resume-alt-1" in driver._resume_response_meta
    finally:
        driver.close()
