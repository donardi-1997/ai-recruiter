import asyncio
import base64
import io
import zipfile

from tools.indeed_resume_agent.browser import (
    BrowserOutcome,
    DOCX_CONTENT_TYPE,
)
from tools.indeed_resume_agent.browser_use_driver import (
    IndeedBrowserUse,
    _candidate_search_queries,
    _candidate_search_url,
    _decode_filename,
    _is_resume_download_url,
    _normalize_lookup_text,
    _safe_indeed_url,
)
from tools.indeed_resume_agent.config import AgentConfig


def config(tmp_path):
    return AgentConfig(
        api_base_url="https://example.com",
        browser_profile_dir=tmp_path / "profile",
        request_timeout_seconds=1.0,
    )


def make_docx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


def test_lookup_normalization_and_queries_handle_accents_and_long_names():
    assert _normalize_lookup_text("  Alejándra   Camacho Sáenz ") == "alejandra camacho saenz"
    assert _candidate_search_queries("Alejándra Camacho Sáenz") == [
        "Alejándra Camacho Sáenz",
        "alejandra camacho saenz",
        "alejandra saenz",
    ]


def test_candidate_search_url_uses_observed_manage_all_route():
    url = _candidate_search_url("Alejandra Camacho Saenz")
    assert url.startswith(
        "https://employers.indeed.com/candidates?statusName=All&tab=manage&q="
    )
    assert "Alejandra+Camacho+Saenz" in url


def test_safe_indeed_url_rejects_external_hosts():
    assert _safe_indeed_url("https://evil.example/resume") == (
        "https://employers.indeed.com/candidates"
    )
    assert _safe_indeed_url(
        "https://employers.indeed.com/candidates/view?id=1"
    ).startswith("https://employers.indeed.com/")


def test_resume_endpoint_matching_is_exact():
    assert _is_resume_download_url(
        "https://employers.indeed.com/api/catws/resume/v2/download?token=secret"
    )
    assert not _is_resume_download_url(
        "https://employers.indeed.com/api/catws/resume/v2/download-extra"
    )
    assert not _is_resume_download_url(
        "https://t.indeed.com/signals/gnav/log"
    )


def test_content_disposition_filename_supports_rfc5987_and_encoded_words():
    assert _decode_filename(
        "attachment; filename*=UTF-8''CV%20Alejandra.docx"
    ) == "CV Alejandra.docx"
    assert _decode_filename(
        'attachment; filename="=?UTF-8?Q?CVAlejandracamachosaenz.docx?="'
    ) == "CVAlejandracamachosaenz.docx"


def test_duplicate_candidates_are_fail_closed_and_job_can_disambiguate(tmp_path):
    rows = [
        {
            "name": "Alejandra Camacho Saenz",
            "rowText": "Alejandra Camacho Saenz Developer",
            "href": "https://employers.indeed.com/candidates/view?id=1",
        },
        {
            "name": "Alejandra Camacho Saenz",
            "rowText": "Alejandra Camacho Saenz Accountant",
            "href": "https://employers.indeed.com/candidates/view?id=2",
        },
    ]
    target, error = IndeedBrowserUse._select_candidate(
        rows,
        "Alejándra Camacho Sáenz",
        "Developer",
    )
    assert error is None
    assert target and str(target["href"]).endswith("id=1")

    target, error = IndeedBrowserUse._select_candidate(
        rows,
        "Alejandra Camacho Saenz",
        None,
    )
    assert target is None
    assert error == "INDEED_CANDIDATE_AMBIGUOUS"


def test_row_only_namecell_remains_clickable_without_anchor():
    rows = [
        {
            "name": "Alejandra Camacho Saenz",
            "rowText": "Alejandra Camacho Saenz Developer",
            "href": "",
            "index": 7,
        }
    ]

    target, error = IndeedBrowserUse._select_candidate(
        rows,
        "Alejándra Camacho Sáenz",
        "Developer",
    )

    assert error is None
    assert target is not None
    assert target["href"] == ""
    assert target["index"] == 7


def test_download_control_wait_tolerates_delayed_spa_mount(tmp_path):
    driver = IndeedBrowserUse(
        config(tmp_path),
        browser_session_class=object,
        browser_executable_resolver=lambda: "chrome.exe",
    )
    attempts = {"count": 0}

    async def no_human(_cdp):
        return False

    async def delayed_control(_cdp):
        attempts["count"] += 1
        return attempts["count"] >= 3

    driver._requires_human = no_human
    driver._click_download_control = delayed_control
    try:
        clicked = driver._call(
            driver._click_download_when_ready(object(), timeout_seconds=1.5),
            timeout=2,
        )
        assert clicked is True
        assert attempts["count"] == 3
    finally:
        driver.close()


def test_download_label_normalization_collapses_whitespace():
    import inspect

    source = inspect.getsource(IndeedBrowserUse._click_download_control)
    assert r".replace(/\s+/g, ' ')" in source
    assert ".replace(/s+/g, ' ')" not in source


def test_browser_use_driver_uses_single_managed_chrome_semantics(tmp_path):
    driver = IndeedBrowserUse(
        config(tmp_path),
        browser_session_class=object,
        browser_executable_resolver=lambda: "chrome.exe",
    )
    try:
        assert driver.browser_label == "Google Chrome"
        assert driver.manual_session_open is False
    finally:
        driver.close()


def test_network_response_body_becomes_original_docx_without_download_folder(tmp_path):
    payload = make_docx_bytes()

    class FakeNetwork:
        async def getResponseBody(self, *, params, session_id):
            assert params == {"requestId": "request-1"}
            assert session_id == "session-1"
            return {
                "body": base64.b64encode(payload).decode("ascii"),
                "base64Encoded": True,
            }

    class FakeSend:
        def __init__(self):
            self.Network = FakeNetwork()

    class FakeClient:
        def __init__(self):
            self.send = FakeSend()

    class FakeBrowser:
        def __init__(self):
            self.cdp_client = FakeClient()

        async def stop(self):
            return None

    driver = IndeedBrowserUse(
        config(tmp_path),
        browser_session_class=object,
        browser_executable_resolver=lambda: "chrome.exe",
    )
    driver._browser = FakeBrowser()

    async def exercise():
        future = driver._arm_download()
        driver._resume_response_meta["request-1"] = {
            "headers": {
                "content-type": DOCX_CONTENT_TYPE,
                "content-disposition": (
                    "attachment; "
                    "filename*=UTF-8''CVAlejandracamachosaenz.docx"
                ),
            },
            "content_type": DOCX_CONTENT_TYPE,
            "session_id": "session-1",
            "url": (
                "https://employers.indeed.com"
                "/api/catws/resume/v2/download"
            ),
        }
        await driver._capture_resume_body("request-1", "session-1")
        return await asyncio.wait_for(future, timeout=1)

    try:
        result = driver._call(exercise(), timeout=2)
        assert result.outcome is BrowserOutcome.DOWNLOADED
        assert result.filename == "CVAlejandracamachosaenz.docx"
        assert result.content_type == DOCX_CONTENT_TYPE
        assert result.data == payload
    finally:
        driver.close()
