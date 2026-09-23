import asyncio

from tools.indeed_resume_agent.browser import BrowserOutcome, PDF_CONTENT_TYPE
from tools.indeed_resume_agent.browser_use_driver import IndeedBrowserUse
from tools.indeed_resume_agent.config import AgentConfig


def _config(tmp_path):
    return AgentConfig(
        api_base_url="https://example.com",
        browser_profile_dir=tmp_path / "profile",
        request_timeout_seconds=0.1,
    )


def test_completed_browser_download_is_recovered_when_network_body_is_not_observed(tmp_path):
    driver = IndeedBrowserUse(
        _config(tmp_path),
        browser_session_class=object,
        browser_executable_resolver=lambda: "chrome.exe",
    )
    try:
        downloads = tmp_path / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        baseline = driver._download_snapshot()
        downloaded = downloads / "CVARLEYMORALESUSMA.pdf"
        downloaded.write_bytes(b"%PDF-1.7\nresume payload")

        async def exercise():
            future = driver._arm_download()
            return await driver._wait_for_download(
                future,
                baseline=baseline,
                timeout_seconds=0.5,
            )

        result = driver._call(exercise(), timeout=2)

        assert result is not None
        assert result.outcome is BrowserOutcome.DOWNLOADED
        assert result.filename == "CVARLEYMORALESUSMA.pdf"
        assert result.content_type == PDF_CONTENT_TYPE
        assert result.data == b"%PDF-1.7\nresume payload"
    finally:
        driver.close()


def test_incomplete_chrome_partial_file_is_not_treated_as_resume(tmp_path):
    driver = IndeedBrowserUse(
        _config(tmp_path),
        browser_session_class=object,
        browser_executable_resolver=lambda: "chrome.exe",
    )
    try:
        downloads = tmp_path / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        baseline = driver._download_snapshot()
        (downloads / "resume.pdf.crdownload").write_bytes(b"%PDF-1.7\npartial")

        async def exercise():
            future = driver._arm_download()
            return await driver._wait_for_download(
                future,
                baseline=baseline,
                timeout_seconds=0.15,
            )

        result = driver._call(exercise(), timeout=2)
        assert result is None
    finally:
        driver.close()
