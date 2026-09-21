import json
from pathlib import Path
import pytest

from tools.indeed_resume_agent.browser import (
    BrowserOutcome,
    IndeedBrowser,
    InvalidResumePdf,
    normalize_pdf_filename,
    validate_pdf,
    _DOWNLOAD_NAME,
    _safe_diagnostic_url,
)
from tools.indeed_resume_agent.config import AgentConfig


class FakeResponse:
    def __init__(self, status=200, content_type="text/html", body=b""):
        self.status = status
        self.headers = {"content-type": content_type}
        self._body = body
    def body(self):
        return self._body


class FakeRequestContext:
    def __init__(self, response):
        self.response = response
        self.urls = []
    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.response


class FakeLocator:
    def __init__(self, count=0, click=None):
        self._count = count
        self._click = click
    def count(self):
        return self._count
    @property
    def first(self):
        return self
    def click(self):
        if self._click:
            self._click()


class FakeDownload:
    suggested_filename = "candidate-cv.pdf"
    def __init__(self, path): self._path = path
    def path(self): return str(self._path)


class FakeDownloadInfo:
    def __init__(self, download): self.value = download


class FakeExpectDownload:
    def __init__(self, download): self.download = download
    def __enter__(self): return FakeDownloadInfo(self.download)
    def __exit__(self, *args): return False


class FakePage:
    def __init__(self, *, url="https://indeed.test/resume", text="", download=None):
        self.url = url
        self._text = text
        self._download = download
        self.goto_urls = []
    def goto(self, url, **kwargs):
        self.goto_urls.append(url)
        self.url = url
        return FakeResponse(200, "text/html", b"")
    def locator(self, selector):
        if selector == "body":
            class Body:
                def __init__(self, text): self.text=text
                def inner_text(self, timeout=None): return self.text
            return Body(self._text)
        return FakeLocator(0)
    def get_by_role(self, role, name=None):
        if self._download and role in {"button", "link"}:
            return FakeLocator(1)
        return FakeLocator(0)
    def expect_download(self, timeout=None):
        return FakeExpectDownload(self._download)


class FakeContext:
    def __init__(self, response, page):
        self.request = FakeRequestContext(response)
        self.pages = [page]
        self.closed = False
    def new_page(self): return self.pages[0]
    def close(self): self.closed=True


class FakeChromium:
    def __init__(self, context):
        self.context=context
        self.kwargs=None
    def launch_persistent_context(self, **kwargs):
        self.kwargs=kwargs
        return self.context


class FakePlaywright:
    def __init__(self, chromium): self.chromium=chromium
    def stop(self): pass


class FakeManager:
    def __init__(self, p): self.p=p
    def start(self): return self.p


class FakeProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode
    def poll(self):
        return self.returncode


def cfg(tmp_path):
    return AgentConfig(api_base_url="https://agent.test", browser_profile_dir=tmp_path / "profile")


def test_start_uses_dedicated_visible_edge_profile_with_sandbox(tmp_path):
    context=FakeContext(FakeResponse(), FakePage())
    chromium=FakeChromium(context)
    browser=IndeedBrowser(cfg(tmp_path), playwright_factory=lambda: FakeManager(FakePlaywright(chromium)))
    browser.start()
    assert (tmp_path / "profile").is_dir()
    assert chromium.kwargs == {
        "user_data_dir": str(tmp_path / "profile"),
        "channel": "msedge",
        "headless": False,
        "accept_downloads": True,
        "chromium_sandbox": True,
    }
    browser.close()
    assert context.closed


def test_open_indeed_uses_normal_edge_with_same_dedicated_profile(tmp_path):
    context=FakeContext(FakeResponse(), FakePage())
    chromium=FakeChromium(context)
    calls=[]

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
        edge_executable_resolver=lambda: r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        process_runner=run,
    )
    browser.start()
    browser.open_indeed()

    assert context.closed is True
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[0].endswith("msedge.exe")
    assert f"--user-data-dir={tmp_path / 'profile'}" in command
    assert "--new-window" in command
    assert "--no-sandbox" not in command
    assert not any(item.startswith("--remote-debugging") for item in command)
    assert command[-1] == "https://www.indeed.com/"
    assert kwargs == {}
    assert browser.manual_session_open is True


def test_start_refuses_profile_while_manual_edge_is_open(tmp_path):
    process = FakeProcess()
    browser=IndeedBrowser(
        cfg(tmp_path),
        edge_executable_resolver=lambda: r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
        process_runner=lambda command: process,
    )
    browser.open_indeed()

    with pytest.raises(RuntimeError, match="INDEED_MANUAL_BROWSER_OPEN"):
        browser.start()

    process.returncode = 0
    assert browser.manual_session_open is False


def test_direct_authenticated_request_returns_pdf_without_page_navigation(tmp_path):
    page=FakePage()
    context=FakeContext(FakeResponse(200, "application/pdf", b"%PDF-direct"), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(cfg(tmp_path), playwright_factory=lambda: FakeManager(FakePlaywright(chromium)))
    browser.start()
    result=browser.fetch_resume("https://indeed.test/resume")
    assert result.outcome is BrowserOutcome.DOWNLOADED
    assert result.data == b"%PDF-direct"
    assert page.goto_urls == []


def test_login_or_challenge_returns_needs_human(tmp_path):
    page=FakePage(url="https://indeed.test/account/login", text="Sign in - security verification CAPTCHA")
    context=FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(cfg(tmp_path), playwright_factory=lambda: FakeManager(FakePlaywright(chromium)))
    browser.start()
    result=browser.fetch_resume("https://indeed.test/resume")
    assert result.outcome is BrowserOutcome.NEEDS_HUMAN
    assert result.human_code == "INDEED_AUTH_REQUIRED"


def test_known_download_control_reads_pdf(tmp_path):
    pdf=tmp_path / "download.pdf"
    pdf.write_bytes(b"%PDF-downloaded")
    page=FakePage(download=FakeDownload(pdf))
    context=FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(cfg(tmp_path), playwright_factory=lambda: FakeManager(FakePlaywright(chromium)))
    browser.start()
    result=browser.fetch_resume("https://indeed.test/resume")
    assert result.outcome is BrowserOutcome.DOWNLOADED
    assert result.filename == "candidate-cv.pdf"
    assert result.data == b"%PDF-downloaded"


def test_unknown_ui_fails_closed(tmp_path):
    page=FakePage(text="Profile page without known controls")
    context=FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(cfg(tmp_path), playwright_factory=lambda: FakeManager(FakePlaywright(chromium)))
    browser.start()
    result=browser.fetch_resume("https://indeed.test/resume")
    assert result.outcome is BrowserOutcome.NEEDS_HUMAN
    assert result.human_code == "INDEED_UI_REQUIRES_REVIEW"
    assert result.diagnostic_path is not None
    payload = json.loads((tmp_path / "diagnostics" / (Path(result.diagnostic_path).name)).read_text(encoding="utf-8"))
    assert payload["url"] == "https://indeed.test/resume"
    assert "?" not in payload["url"]


@pytest.mark.parametrize("data,code", [(b"", "RESUME_NOT_PDF"), (b"hello", "RESUME_NOT_PDF")])
def test_validate_pdf_rejects_non_pdf(data, code):
    with pytest.raises(InvalidResumePdf) as exc:
        validate_pdf(data, max_bytes=100)
    assert exc.value.code == code


def test_validate_pdf_rejects_oversize():
    with pytest.raises(InvalidResumePdf) as exc:
        validate_pdf(b"%PDF-" + b"x"*100, max_bytes=10)
    assert exc.value.code == "RESUME_TOO_LARGE"


def test_normalize_pdf_filename_removes_paths_and_forces_pdf_extension():
    assert normalize_pdf_filename(r"C:\temp\Ada Resume.exe") == "Ada Resume.pdf"
    assert normalize_pdf_filename("../../evil.pdf") == "evil.pdf"


def test_open_indeed_can_open_specific_safe_resume_url(tmp_path):
    calls=[]

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    browser=IndeedBrowser(
        cfg(tmp_path),
        edge_executable_resolver=lambda: r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        process_runner=run,
    )
    browser.open_indeed("https://employers.indeed.com/resume/ada")

    assert calls[0][0][-1] == "https://employers.indeed.com/resume/ada"


@pytest.mark.parametrize(
    "url",
    [
        "http://employers.indeed.com/resume/ada",
        "https://indeed.com.evil.example/resume/ada",
        "javascript:alert(1)",
    ],
)
def test_open_indeed_rejects_unsafe_manual_url(tmp_path, url):
    calls=[]

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    browser=IndeedBrowser(
        cfg(tmp_path),
        edge_executable_resolver=lambda: r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        process_runner=run,
    )
    browser.open_indeed(url)

    assert calls[0][0][-1] == "https://www.indeed.com/"


@pytest.mark.parametrize(
    "label",
    [
        "Download resume",
        "Download CV",
        "Descargar currículum",
        "Descargar hoja de vida",
        "Ver CV",
        "View resume",
    ],
)
def test_download_control_name_accepts_common_indeed_labels(label):
    assert _DOWNLOAD_NAME.fullmatch(label)


def test_safe_diagnostic_url_strips_query_and_fragment():
    assert _safe_diagnostic_url(
        "https://employers.indeed.com/resume/abc?token=secret#section"
    ) == "https://employers.indeed.com/resume/abc"


def test_known_control_that_does_not_download_becomes_human_review(tmp_path):
    class ControlWithoutDownloadPage(FakePage):
        def get_by_role(self, role, name=None):
            if role == "button":
                return FakeLocator(1)
            return FakeLocator(0)

        def expect_download(self, timeout=None):
            raise RuntimeError("download did not start")

    page=ControlWithoutDownloadPage(text="Candidate profile")
    context=FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )
    browser.start()

    result=browser.fetch_resume("https://indeed.test/resume")

    assert result.outcome is BrowserOutcome.NEEDS_HUMAN
    assert result.human_code == "INDEED_DOWNLOAD_ACTION_REQUIRES_REVIEW"
    assert result.diagnostic_path is not None
