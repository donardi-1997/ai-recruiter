import io
import json
from pathlib import Path
import zipfile
import pytest

from tools.indeed_resume_agent.browser import (
    BrowserFetchStageError,
    BrowserOutcome,
    IndeedBrowser,
    DOCX_CONTENT_TYPE,
    PDF_CONTENT_TYPE,
    InvalidResumeDocument,
    InvalidResumePdf,
    normalize_pdf_filename,
    normalize_resume_filename,
    validate_pdf,
    validate_resume_document,
    _DOWNLOAD_NAME,
    _safe_diagnostic_url,
    _safe_diagnostic_text,
)
from tools.indeed_resume_agent.config import AgentConfig


class FakeResponse:
    def __init__(
        self,
        status=200,
        content_type="text/html",
        body=b"",
        *,
        content_disposition=None,
        url="",
    ):
        self.status = status
        self.headers = {"content-type": content_type}
        if content_disposition is not None:
            self.headers["content-disposition"] = content_disposition
        self.url = url
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
    def __init__(self, path, suggested_filename="candidate-cv.pdf"):
        self._path = path
        self.suggested_filename = suggested_filename
    def path(self): return str(self._path)


def _docx_bytes(text="Alejandra Camacho Saenz"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        )
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>',
        )
    return buffer.getvalue()


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


def test_playwright_context_is_not_misclassified_as_manual_browser(tmp_path):
    page = FakePage(url="https://employers.indeed.com/candidates")
    context = FakeContext(FakeResponse(), page)
    browser = IndeedBrowser(
        cfg(tmp_path),
        manual_process_probe=lambda profile_dir: True,
    )
    browser._context = context

    assert browser.manual_session_open is False


def test_start_relaunches_after_user_closes_previous_playwright_window(tmp_path):
    class ClosedPage(FakePage):
        def is_closed(self):
            return True

    stale_context = FakeContext(FakeResponse(), ClosedPage())
    stale_chromium = FakeChromium(stale_context)
    fresh_context = FakeContext(FakeResponse(), FakePage())
    fresh_chromium = FakeChromium(fresh_context)

    browser = IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(fresh_chromium)),
    )
    browser._context = stale_context
    browser._playwright = FakePlaywright(stale_chromium)

    browser.start()

    assert stale_context.closed is True
    assert browser._context is fresh_context
    assert fresh_chromium.kwargs["channel"] == "chrome"


def test_start_uses_dedicated_visible_chrome_profile_with_sandbox(tmp_path):
    context=FakeContext(FakeResponse(), FakePage())
    chromium=FakeChromium(context)
    browser=IndeedBrowser(cfg(tmp_path), playwright_factory=lambda: FakeManager(FakePlaywright(chromium)))
    browser.start()
    assert (tmp_path / "profile").is_dir()
    assert chromium.kwargs == {
        "user_data_dir": str(tmp_path / "profile"),
        "channel": "chrome",
        "headless": False,
        "accept_downloads": True,
        "chromium_sandbox": True,
    }
    browser.close()
    assert context.closed


def test_open_indeed_uses_normal_chrome_with_same_dedicated_profile(tmp_path):
    context=FakeContext(FakeResponse(), FakePage())
    chromium=FakeChromium(context)
    calls=[]

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
        browser_executable_resolver=lambda: r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        process_runner=run,
    )
    browser.start()
    browser.open_indeed()

    assert context.closed is True
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[0].endswith("chrome.exe")
    assert f"--user-data-dir={tmp_path / 'profile'}" in command
    assert "--new-window" in command
    assert "--no-sandbox" not in command
    assert not any(item.startswith("--remote-debugging") for item in command)
    assert command[-1] == "https://employers.indeed.com/candidates"
    assert kwargs == {}
    assert browser.manual_session_open is True


def test_open_indeed_reissues_launch_when_profile_process_already_exists(tmp_path):
    calls=[]
    process=FakeProcess(returncode=None)

    browser=IndeedBrowser(
        cfg(tmp_path),
        browser_executable_resolver=lambda: r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        process_runner=lambda command: calls.append(command) or process,
        manual_process_probe=lambda profile_dir: True,
    )
    browser._manual_process = process

    browser.open_indeed()

    assert len(calls) == 1
    assert calls[0][-1] == "https://employers.indeed.com/candidates"


def test_start_refuses_profile_while_manual_edge_is_open(tmp_path):
    process = FakeProcess()
    browser=IndeedBrowser(
        cfg(tmp_path),
        browser_executable_resolver=lambda: r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        process_runner=lambda command: process,
    )
    browser.open_indeed()

    with pytest.raises(RuntimeError, match="INDEED_MANUAL_BROWSER_OPEN"):
        browser.start()

    process.returncode = 0
    assert browser.manual_session_open is False


def test_manual_session_detects_edge_child_after_launcher_exits(tmp_path):
    process = FakeProcess(returncode=0)
    checks = []

    def probe(profile_dir):
        checks.append(profile_dir)
        return True

    browser=IndeedBrowser(
        cfg(tmp_path),
        browser_executable_resolver=lambda: r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        process_runner=lambda command: process,
        manual_process_probe=probe,
    )
    browser.open_indeed()

    assert browser.manual_session_open is True
    assert checks == [tmp_path / "profile"]


def test_manual_session_clears_when_launcher_and_profile_process_are_gone(tmp_path):
    process = FakeProcess(returncode=0)
    browser=IndeedBrowser(
        cfg(tmp_path),
        browser_executable_resolver=lambda: r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        process_runner=lambda command: process,
        manual_process_probe=lambda profile_dir: False,
    )
    browser.open_indeed()

    assert browser.manual_session_open is False


def test_diagnostic_materializes_second_keep_alive_page(tmp_path):
    class AnchorPage(FakePage):
        def __init__(self):
            super().__init__(url="about:blank", text="")
            self.content = ""
            self.front_calls = 0

        def set_content(self, content):
            self.content = content

        def bring_to_front(self):
            self.front_calls += 1

        def wait_for_timeout(self, timeout):
            return None

    class MultiPageContext(FakeContext):
        def __init__(self, response, page):
            super().__init__(response, page)
            self.handlers = {}
            self.anchor = AnchorPage()

        def on(self, name, callback):
            self.handlers[name] = callback

        def new_page(self):
            if self.anchor not in self.pages:
                self.pages.append(self.anchor)
            return self.anchor

    page = FakePage(url="https://employers.indeed.com/candidates", text="Candidates")
    context = MultiPageContext(FakeResponse(), page)
    chromium = FakeChromium(context)
    browser = IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )

    browser.start_diagnostic()

    assert len(context.pages) == 2
    assert "ASIATI — KEEP OPEN" in context.anchor.content
    assert browser._diagnostic_anchor_page_id == id(context.anchor)
    ready = [
        event for event in browser._diagnostic_events
        if event.get("kind") == "diagnostic_pages_ready"
    ]
    assert ready[-1]["page_count"] == 2
    assert ready[-1]["anchor_created"] is True


def test_diagnostic_requires_manual_login_instead_of_automating_auth(tmp_path):
    page=FakePage(
        url="https://employers.indeed.com/account/login",
        text="Iniciar sesión",
    )
    context=FakeContext(FakeResponse(), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )

    with pytest.raises(RuntimeError, match="INDEED_MANUAL_LOGIN_REQUIRED"):
        browser.start_diagnostic()

    assert browser.diagnostic_active is False
    assert context.closed is True


def test_diagnostic_detects_captcha_iframe_and_exits_automation(tmp_path):
    class CaptchaPage(FakePage):
        def locator(self, selector):
            if selector == "body":
                return super().locator(selector)
            if "captcha" in selector:
                return FakeLocator(1)
            return FakeLocator(0)

    page=CaptchaPage(
        url="https://employers.indeed.com/candidates",
        text="Verificando navegador",
    )
    context=FakeContext(FakeResponse(), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )

    with pytest.raises(RuntimeError, match="INDEED_MANUAL_LOGIN_REQUIRED"):
        browser.start_diagnostic()

    assert browser.diagnostic_active is False
    assert context.closed is True


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


@pytest.mark.parametrize(
    "content_type",
    [
        "application/octet-stream",
        "binary/octet-stream",
        "text/html",
        "",
    ],
)
def test_direct_authenticated_request_accepts_pdf_magic_with_non_pdf_mime(tmp_path, content_type):
    page=FakePage()
    context=FakeContext(FakeResponse(200, content_type, b"%PDF-mislabeled"), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )
    browser.start()

    result=browser.fetch_resume("https://indeed.test/resume")

    assert result.outcome is BrowserOutcome.DOWNLOADED
    assert result.data == b"%PDF-mislabeled"
    assert page.goto_urls == []


def test_declared_pdf_with_invalid_body_still_fails_validation(tmp_path):
    page=FakePage()
    context=FakeContext(FakeResponse(200, "application/pdf", b"<html></html>"), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )
    browser.start()

    with pytest.raises(InvalidResumePdf) as exc:
        browser.fetch_resume("https://indeed.test/resume")

    assert exc.value.code == "RESUME_NOT_PDF"


def test_login_or_challenge_returns_needs_human(tmp_path):
    page=FakePage(url="https://indeed.test/account/login", text="Sign in - security verification CAPTCHA")
    context=FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(cfg(tmp_path), playwright_factory=lambda: FakeManager(FakePlaywright(chromium)))
    browser.start()
    result=browser.fetch_resume("https://indeed.test/resume")
    assert result.outcome is BrowserOutcome.NEEDS_HUMAN
    assert result.human_code == "INDEED_AUTH_REQUIRED"


def test_html_navigation_body_unavailable_does_not_abort_download_flow(tmp_path):
    pdf=tmp_path / "download.pdf"
    pdf.write_bytes(b"%PDF-downloaded")

    class HtmlResponseWithUnavailableBody:
        status = 200
        url = "https://employers.indeed.com/candidates/view?id=abc"
        headers = {"content-type": "text/html; charset=utf-8"}

        def body(self):
            raise RuntimeError("Protocol error: body unavailable after navigation commit")

    class LandedPage(FakePage):
        def goto(self, url, **kwargs):
            self.goto_urls.append(url)
            self.url = "https://employers.indeed.com/candidates/view?id=abc"
            return HtmlResponseWithUnavailableBody()

    page=LandedPage(download=FakeDownload(pdf))
    context=FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )
    browser.start()

    result=browser.fetch_resume("https://indeed.test/resume")

    assert result.outcome is BrowserOutcome.DOWNLOADED
    assert result.data == b"%PDF-downloaded"
    assert page.url == "https://employers.indeed.com/candidates/view?id=abc"


def test_navigation_failure_has_specific_safe_stage_code(tmp_path):
    class FailingPage(FakePage):
        def goto(self, url, **kwargs):
            raise RuntimeError("secret signed URL should not leak")

    page=FailingPage()
    context=FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )
    browser.start()

    with pytest.raises(BrowserFetchStageError) as exc:
        browser.fetch_resume("https://indeed.test/resume")

    assert exc.value.code == "RESUME_BROWSER_NAVIGATION_FAILED"
    assert "secret" not in str(exc.value)


def test_known_download_control_uses_pdf_response_if_browser_closes(tmp_path):
    class ResumeResponse:
        status = 200
        url = "https://employers.indeed.com/api/catws/resume/v2/download?candidate=secret"
        headers = {
            "content-type": "application/pdf",
            "content-disposition": (
                'attachment; filename="=?UTF-8?Q?CVNatalyFraile.pdf?="; '
                "filename*=UTF-8''CVNatalyFraile.pdf"
            ),
        }

        def body(self):
            return b"%PDF-network-response"

    class ClosingExpectDownload:
        def __enter__(self):
            return FakeDownloadInfo(None)

        def __exit__(self, exc_type, exc, tb):
            raise RuntimeError("Target page, context or browser has been closed")

    class ClosingPage(FakePage):
        def __init__(self):
            super().__init__(url="https://employers.indeed.com/candidates/view")
            self.handlers = {}

        def on(self, name, callback):
            self.handlers[name] = callback

        def off(self, name, callback):
            if self.handlers.get(name) is callback:
                self.handlers.pop(name, None)

        def get_by_role(self, role, name=None):
            if role == "button":
                return FakeLocator(1, click=self._click_download)
            return FakeLocator(0)

        def expect_download(self, timeout=None):
            return ClosingExpectDownload()

        def _click_download(self):
            self.handlers["response"](ResumeResponse())

    page = ClosingPage()
    context = FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium = FakeChromium(context)
    browser = IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )
    browser.start()

    result = browser.fetch_resume("https://employers.indeed.com/candidates/view?id=abc")

    assert result.outcome is BrowserOutcome.DOWNLOADED
    assert result.filename == "CVNatalyFraile.pdf"
    assert result.data == b"%PDF-network-response"


def test_resume_download_response_requires_exact_indeed_endpoint(tmp_path):
    browser = IndeedBrowser(cfg(tmp_path))

    class Response:
        status = 200
        url = "https://employers.indeed.com/api/catws/resume/v2/download?candidate=abc"

    assert browser._is_resume_download_response(Response()) is True

    Response.url = "https://evil.example/api/catws/resume/v2/download"
    assert browser._is_resume_download_response(Response()) is False


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


def test_spa_waits_for_download_control_before_requiring_review(tmp_path):
    pdf=tmp_path / "download.pdf"
    pdf.write_bytes(b"%PDF-delayed")

    class DelayedControlPage(FakePage):
        def __init__(self):
            super().__init__(url="https://employers.indeed.com/candidates/resume", download=FakeDownload(pdf))
            self.probes = 0

        def get_by_role(self, role, name=None):
            self.probes += 1
            if self.probes < 5:
                return FakeLocator(0)
            return FakeLocator(1)

    page=DelayedControlPage()
    context=FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )
    browser.start()

    result=browser.fetch_resume("https://indeed.test/resume")

    assert result.outcome is BrowserOutcome.DOWNLOADED
    assert result.data == b"%PDF-delayed"
    assert page.probes >= 5


def test_direct_candidates_workspace_is_preferred_over_left_rail(tmp_path):
    pdf=tmp_path / "download.pdf"
    pdf.write_bytes(b"%PDF-direct")

    class CandidateLocator(FakeLocator):
        def __init__(self, page):
            super().__init__(1)
            self.page = page

        def click(self):
            self.page.url = "https://employers.indeed.com/candidates/view?id=alejandra"
            self.page.candidate_open = True

    class DirectCandidatesPage(FakePage):
        def __init__(self):
            super().__init__(
                url="https://resumes.indeed.com/?from=gnav-one-host",
                download=FakeDownload(pdf),
            )
            self.candidate_open = False
            self.rail_clicked = False

        def goto(self, url, **kwargs):
            self.goto_urls.append(url)
            if url == "https://employers.indeed.com/candidates":
                self.url = url
                return FakeResponse(200, "text/html", b"")
            return super().goto(url, **kwargs)

        def locator(self, selector):
            if selector == "body":
                return super().locator(selector)
            if (
                self.url.startswith("https://employers.indeed.com/candidates")
                and selector == '[data-testid="candidate-list-table-container"]'
            ):
                return FakeLocator(1)
            return FakeLocator(0)

        def get_by_text(self, pattern):
            if self.url.startswith("https://employers.indeed.com/candidates"):
                return CandidateLocator(self)
            return FakeLocator(0)

        def get_by_role(self, role, name=None):
            if self.candidate_open and role in {"button", "link"}:
                return FakeLocator(1)
            return FakeLocator(0)

        def wait_for_timeout(self, timeout):
            return None

    page=DirectCandidatesPage()
    context=FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )
    browser.start()

    result=browser.fetch_resume(
        "https://indeed.test/resume",
        candidate_name="Alejandra camacho saenz",
    )

    assert result.outcome is BrowserOutcome.DOWNLOADED
    assert result.data == b"%PDF-direct"
    assert "https://employers.indeed.com/candidates" in page.goto_urls
    assert page.candidate_open is True


def test_left_rail_is_only_fallback_when_direct_candidates_route_redirects(tmp_path):
    pdf=tmp_path / "download.pdf"
    pdf.write_bytes(b"%PDF-rail")

    class NavigationLocator(FakeLocator):
        def __init__(self, page):
            super().__init__(1)
            self.page = page

        def click(self):
            self.page.url = "https://employers.indeed.com/candidates/manage"
            self.page.in_candidates = True

    class CandidateLocator(FakeLocator):
        def __init__(self, page):
            super().__init__(1)
            self.page = page

        def click(self):
            self.page.url = "https://employers.indeed.com/candidates/view?id=alejandra"
            self.page.candidate_open = True

    class RedirectThenRailPage(FakePage):
        def __init__(self):
            super().__init__(
                url="https://resumes.indeed.com/?from=gnav-one-host",
                download=FakeDownload(pdf),
            )
            self.in_candidates = False
            self.candidate_open = False

        def goto(self, url, **kwargs):
            self.goto_urls.append(url)
            if url == "https://employers.indeed.com/candidates":
                self.url = "https://resumes.indeed.com/?from=gnav-one-host"
                return FakeResponse(200, "text/html", b"")
            return super().goto(url, **kwargs)

        def get_by_role(self, role, name=None):
            if (
                not self.in_candidates
                and role in {"link", "button"}
                and hasattr(name, "search")
                and name.search("Candidatos")
            ):
                return NavigationLocator(self)
            if self.candidate_open and role in {"button", "link"}:
                return FakeLocator(1)
            return FakeLocator(0)

        def locator(self, selector):
            if selector == "body":
                return super().locator(selector)
            if self.in_candidates and selector == '[data-testid="candidate-list-table-container"]':
                return FakeLocator(1)
            return FakeLocator(0)

        def get_by_text(self, pattern):
            if self.in_candidates:
                return CandidateLocator(self)
            return FakeLocator(0)

        def wait_for_timeout(self, timeout):
            return None

    page=RedirectThenRailPage()
    context=FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )
    browser.start()

    result=browser.fetch_resume(
        "https://indeed.test/resume",
        candidate_name="Alejandra camacho saenz",
    )

    assert result.outcome is BrowserOutcome.DOWNLOADED
    assert result.data == b"%PDF-rail"
    assert "https://employers.indeed.com/candidates" in page.goto_urls
    assert page.in_candidates is True
    assert page.candidate_open is True


def test_generic_resume_landing_falls_back_to_candidate_list_by_name(tmp_path):
    pdf=tmp_path / "download.pdf"
    pdf.write_bytes(b"%PDF-fallback")

    class CandidateTextLocator(FakeLocator):
        def __init__(self, page):
            super().__init__(1)
            self.page = page

        def click(self):
            self.page.url = "https://employers.indeed.com/candidates/view?id=alejandra"
            self.page.candidate_open = True

    class CandidateListPage(FakePage):
        def __init__(self):
            super().__init__(
                url="https://resumes.indeed.com/?from=gnav-one-host",
                download=FakeDownload(pdf),
            )
            self.candidate_open = False
            self.fallback_nav = False
            self.wait_calls = 0

        def goto(self, url, **kwargs):
            self.goto_urls.append(url)
            if url == "https://employers.indeed.com/candidates":
                self.url = url
                self.fallback_nav = True
                return FakeResponse(200, "text/html", b"")
            self.url = "https://resumes.indeed.com/?from=gnav-one-host"
            return FakeResponse(200, "text/html", b"")

        def locator(self, selector):
            if selector == "body":
                return super().locator(selector)
            if self.fallback_nav and selector == '[data-testid="candidate-list-table-container"]':
                return FakeLocator(1)
            return FakeLocator(0)

        def get_by_text(self, pattern):
            if (
                self.fallback_nav
                and hasattr(pattern, "pattern")
                and "Alejandra" in pattern.pattern
            ):
                return CandidateTextLocator(self)
            return FakeLocator(0)

        def get_by_role(self, role, name=None):
            if self.candidate_open and role in {"button", "link"}:
                return FakeLocator(1)
            return FakeLocator(0)

        def wait_for_timeout(self, timeout):
            self.wait_calls += 1
            return None

    page=CandidateListPage()
    context=FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )
    browser.start()

    result=browser.fetch_resume(
        "https://indeed.test/resume",
        candidate_name="Alejandra camacho saenz",
    )

    assert result.outcome is BrowserOutcome.DOWNLOADED
    assert result.data == b"%PDF-fallback"
    assert "https://employers.indeed.com/candidates" in page.goto_urls
    assert page.candidate_open is True


def test_candidate_search_uses_observed_status_all_manage_q_route(tmp_path):
    pdf=tmp_path / "download.pdf"
    pdf.write_bytes(b"%PDF-query-route")

    class CandidateLink:
        def __init__(self, page):
            self.page = page
        def inner_text(self, timeout=None):
            return "Alejandra camacho saenz"
        def locator(self, selector):
            return FakeLocator(0)
        def click(self):
            self.page.candidate_open = True
            self.page.url = "https://employers.indeed.com/candidates/view?id=alejandra"

    class CandidateLinks:
        def __init__(self, page):
            self.page = page
        def count(self):
            return 1
        def nth(self, index):
            assert index == 0
            return CandidateLink(self.page)

    class QueryRoutePage(FakePage):
        def __init__(self):
            super().__init__(
                url="https://resumes.indeed.com/?from=gnav-one-host",
                download=FakeDownload(pdf),
            )
            self.candidate_open = False

        def goto(self, url, **kwargs):
            self.goto_urls.append(url)
            self.url = url
            return FakeResponse(200, "text/html", b"")

        def locator(self, selector):
            if selector == "body":
                return super().locator(selector)
            if selector == '[data-testid="candidate-list-table-container"]':
                return FakeLocator(1)
            if (
                'a[data-testid="NameCell"]' in selector
                and "statusName=All&tab=manage&q=Alejandra+camacho+saenz" in self.url
            ):
                return CandidateLinks(self)
            return FakeLocator(0)

        def get_by_role(self, role, name=None):
            if self.candidate_open and role in {"button", "link"}:
                return FakeLocator(1)
            return FakeLocator(0)

        def wait_for_timeout(self, timeout):
            return None

    page=QueryRoutePage()
    context=FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )
    browser.start()

    result=browser.fetch_resume(
        "https://indeed.test/resume",
        candidate_name="Alejandra camacho saenz",
    )

    assert result.outcome is BrowserOutcome.DOWNLOADED
    assert result.data == b"%PDF-query-route"
    assert any(
        url
        == "https://employers.indeed.com/candidates?statusName=All&tab=manage&q=Alejandra+camacho+saenz"
        for url in page.goto_urls
    )


def test_candidate_search_url_encodes_names_safely(tmp_path):
    browser=IndeedBrowser(cfg(tmp_path))
    assert browser._candidate_search_url("Alejandra Camacho Sáenz") == (
        "https://employers.indeed.com/candidates"
        "?statusName=All&tab=manage&q=Alejandra+Camacho+S%C3%A1enz"
    )


def test_candidates_workspace_selects_manage_and_all_stage_before_lookup(tmp_path):
    class TabLocator:
        def __init__(self, page, key):
            self.page = page
            self.key = key
        @property
        def first(self):
            return self
        def count(self):
            return 1
        def get_attribute(self, name):
            if name != "aria-selected":
                return None
            return "true" if self.page.selected[self.key] else "false"
        def click(self):
            self.page.selected[self.key] = True
            self.page.clicks.append(self.key)

    class WorkspacePage(FakePage):
        def __init__(self):
            super().__init__(url="https://resumes.indeed.com/")
            self.selected = {"manage": False, "all": False}
            self.clicks = []

        def goto(self, url, **kwargs):
            self.goto_urls.append(url)
            self.url = "https://employers.indeed.com/candidates"
            return FakeResponse(200, "text/html", b"")

        def locator(self, selector):
            if selector == "body":
                return super().locator(selector)
            if selector == '[data-testid="manage-candidates-tab"]':
                return TabLocator(self, "manage")
            if selector == '[data-testid="stage-tab-All"]':
                return TabLocator(self, "all")
            if selector == '[data-testid="candidate-list-table-container"]':
                return FakeLocator(1 if all(self.selected.values()) else 0)
            return FakeLocator(0)

        def wait_for_timeout(self, timeout):
            return None

    page = WorkspacePage()
    browser = IndeedBrowser(cfg(tmp_path))

    assert browser._open_candidates_workspace(page) is True
    assert page.clicks == ["manage", "all"]
    assert page.selected == {"manage": True, "all": True}


def test_candidate_lookup_uses_live_namecell_dom_and_job_title(tmp_path):
    pdf=tmp_path / "download.pdf"
    pdf.write_bytes(b"%PDF-live-dom")

    class RowLocator:
        def inner_text(self, timeout=None):
            return (
                "ALEJANDRA CAMACHO SÁENZ Bogotá "
                "Empleo que solicitó: Líder de Marketing y Crecimiento"
            )

    class CandidateLink:
        def __init__(self, page):
            self.page = page
        def inner_text(self, timeout=None):
            return "ALEJANDRA CAMACHO SÁENZ"
        def locator(self, selector):
            assert "table-row" in selector
            return RowLocator()
        def click(self):
            self.page.candidate_open = True
            self.page.url = "https://employers.indeed.com/candidates/view?id=alejandra"

    class CandidateLinks:
        def __init__(self, page):
            self.page = page
        def count(self):
            return 1 if self.page.search_query else 0
        def nth(self, index):
            assert index == 0
            return CandidateLink(self.page)

    class SearchInput:
        def __init__(self, page):
            self.page = page
        @property
        def first(self):
            return self
        def count(self):
            return 1
        def fill(self, value):
            self.page.search_query = value
        def press(self, key):
            self.page.pressed.append(key)

    class LiveCandidatesPage(FakePage):
        def __init__(self):
            super().__init__(
                url="https://resumes.indeed.com/?from=gnav-one-host",
                download=FakeDownload(pdf),
            )
            self.search_query = ""
            self.pressed = []
            self.candidate_open = False

        def goto(self, url, **kwargs):
            self.goto_urls.append(url)
            if url == "https://employers.indeed.com/candidates":
                self.url = url
                return FakeResponse(200, "text/html", b"")
            return super().goto(url, **kwargs)

        def locator(self, selector):
            if selector == "body":
                return super().locator(selector)
            if selector == 'input[placeholder="Buscar candidatos" i]':
                return SearchInput(self)
            if 'a[data-testid="NameCell"]' in selector:
                return CandidateLinks(self)
            return FakeLocator(0)

        def get_by_role(self, role, name=None):
            if self.candidate_open and role in {"button", "link"}:
                return FakeLocator(1)
            return FakeLocator(0)

        def wait_for_timeout(self, timeout):
            return None

    page=LiveCandidatesPage()
    context=FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )
    browser.start()

    result=browser.fetch_resume(
        "https://indeed.test/resume",
        candidate_name="Alejandra camacho saenz",
        job_title="Lider de Marketing y Crecimiento",
    )

    assert result.outcome is BrowserOutcome.DOWNLOADED
    assert result.data == b"%PDF-live-dom"
    assert page.candidate_open is True
    assert page.search_query
    assert browser._normalize_lookup_text("SÁENZ") == "saenz"


def test_candidate_lookup_falls_back_to_candidate_rows_when_namecell_anchor_is_absent(tmp_path):
    class ClickTarget(FakeLocator):
        def __init__(self):
            super().__init__(1)
            self.clicked = False
        def click(self):
            self.clicked = True

    target = ClickTarget()

    class Row:
        def __init__(self):
            self.text = (
                "ALEJANDRA CAMACHO SÁENZ Bogotá, Cundinamarca "
                "Empleo que solicitó: Líder de Marketing y Crecimiento"
            )
        @property
        def first(self):
            return self
        def count(self):
            return 1
        def inner_text(self, timeout=None):
            return self.text
        def locator(self, selector):
            if selector == '[data-testid="NameCell"]':
                return target
            return FakeLocator(0)

    row = Row()

    class Rows:
        def count(self):
            return 1
        def nth(self, index):
            assert index == 0
            return row

    class RowOnlyPage(FakePage):
        def locator(self, selector):
            if selector == "body":
                return super().locator(selector)
            if selector == '[data-testid="table-row"]':
                return Rows()
            return FakeLocator(0)

    browser = IndeedBrowser(cfg(tmp_path))
    link, ambiguous = browser._find_exact_candidate_link(
        RowOnlyPage(),
        "Alejandra camacho saenz",
        job_title="Lider de Marketing y Crecimiento",
    )

    assert ambiguous is False
    assert link is target
    assert browser._normalize_lookup_text("SÁENZ") == "saenz"


def test_duplicate_candidate_names_fail_closed_without_job_match(tmp_path):
    class RowLocator:
        def __init__(self, text):
            self.text = text
        def inner_text(self, timeout=None):
            return self.text

    class CandidateLink:
        def __init__(self, text, row):
            self.text = text
            self.row = row
        def inner_text(self, timeout=None):
            return self.text
        def locator(self, selector):
            return RowLocator(self.row)

    class CandidateLinks:
        def __init__(self):
            self.items = [
                CandidateLink("Ada Lovelace", "Empleo que solicitó: Analyst"),
                CandidateLink("ADA LOVELACE", "Empleo que solicitó: Designer"),
            ]
        def count(self):
            return len(self.items)
        def nth(self, index):
            return self.items[index]

    class DuplicatePage(FakePage):
        def locator(self, selector):
            if selector == "body":
                return super().locator(selector)
            if 'a[data-testid="NameCell"]' in selector:
                return CandidateLinks()
            return FakeLocator(0)

    browser=IndeedBrowser(cfg(tmp_path))
    link, ambiguous = browser._find_exact_candidate_link(
        DuplicatePage(),
        "Ada Lovelace",
        job_title="Engineer",
    )

    assert link is None
    assert ambiguous is True


def test_candidate_search_route_returns_not_found_when_name_is_absent(tmp_path):
    class MissingCandidatePage(FakePage):
        def goto(self, url, **kwargs):
            self.goto_urls.append(url)
            self.url = url
            return FakeResponse(200, "text/html", b"")

        def locator(self, selector):
            if selector == "body":
                return super().locator(selector)
            if selector == '[data-testid="candidate-list-table-container"]':
                return FakeLocator(1)
            return FakeLocator(0)

        def get_by_text(self, pattern):
            return FakeLocator(0)

        def wait_for_timeout(self, timeout):
            return None

    page=MissingCandidatePage(url="https://resumes.indeed.com/")
    context=FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )
    browser.start()

    result=browser.fetch_resume(
        "https://indeed.test/resume",
        candidate_name="Alejandra camacho saenz",
    )

    assert result.outcome is BrowserOutcome.NEEDS_HUMAN
    assert result.human_code == "INDEED_CANDIDATE_NOT_FOUND"
    assert result.diagnostic_path is not None


def test_candidate_search_unavailable_when_query_route_and_input_are_missing(tmp_path):
    class SearchUnavailablePage(FakePage):
        def __init__(self):
            super().__init__(url="https://resumes.indeed.com/")
            self.initial_workspace = True

        def goto(self, url, **kwargs):
            self.goto_urls.append(url)
            if "statusName=All&tab=manage&q=" in url:
                self.url = "https://resumes.indeed.com/?from=gnav-one-host"
                self.initial_workspace = False
            else:
                self.url = "https://employers.indeed.com/candidates"
            return FakeResponse(200, "text/html", b"")

        def locator(self, selector):
            if selector == "body":
                return super().locator(selector)
            if (
                self.initial_workspace
                and selector == '[data-testid="candidate-list-table-container"]'
            ):
                return FakeLocator(1)
            return FakeLocator(0)

        def get_by_text(self, pattern):
            return FakeLocator(0)

        def wait_for_timeout(self, timeout):
            return None

    page=SearchUnavailablePage()
    context=FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium=FakeChromium(context)
    browser=IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )
    browser.start()

    result=browser.fetch_resume(
        "https://indeed.test/resume",
        candidate_name="Alejandra camacho saenz",
    )

    assert result.outcome is BrowserOutcome.NEEDS_HUMAN
    assert result.human_code == "INDEED_CANDIDATE_SEARCH_UNAVAILABLE"


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
    assert payload["reason"] == "INDEED_UI_REQUIRES_REVIEW"
    assert payload["inputs"] == []


def test_validate_resume_document_accepts_docx_and_preserves_extension():
    data = _docx_bytes()
    content_type = validate_resume_document(
        data,
        filename="CVAlejandracamachosaenz.docx",
        content_type=DOCX_CONTENT_TYPE,
        max_bytes=15 * 1024 * 1024,
    )
    assert content_type == DOCX_CONTENT_TYPE
    assert normalize_resume_filename(
        r"C:\temp\CVAlejandracamachosaenz.docx",
        content_type=content_type,
    ) == "CVAlejandracamachosaenz.docx"


def test_validate_resume_document_rejects_fake_docx():
    with pytest.raises(InvalidResumeDocument) as caught:
        validate_resume_document(
            b"PK-not-a-real-docx",
            filename="candidate.docx",
            content_type=DOCX_CONTENT_TYPE,
            max_bytes=15 * 1024 * 1024,
        )
    assert caught.value.code == "RESUME_NOT_DOCX"


def test_resume_response_preserves_docx_filename_and_mime(tmp_path):
    browser = IndeedBrowser(cfg(tmp_path))
    response = FakeResponse(
        200,
        DOCX_CONTENT_TYPE,
        _docx_bytes(),
        content_disposition='attachment; filename="CVAlejandracamachosaenz.docx"',
        url="https://employers.indeed.com/api/catws/resume/v2/download",
    )

    document = browser._response_document(response)

    assert document is not None
    data, content_type, filename = document
    assert data.startswith(b"PK")
    assert content_type == DOCX_CONTENT_TYPE
    assert filename == "CVAlejandracamachosaenz.docx"


def test_download_object_accepts_docx_resume(tmp_path):
    docx = tmp_path / "download.docx"
    docx.write_bytes(_docx_bytes())
    page = FakePage(
        download=FakeDownload(
            docx,
            suggested_filename="CVAlejandracamachosaenz.docx",
        )
    )
    context = FakeContext(FakeResponse(200, "text/html", b""), page)
    chromium = FakeChromium(context)
    browser = IndeedBrowser(
        cfg(tmp_path),
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
    )
    browser.start()

    result = browser.fetch_resume(
        "https://indeed.test/resume",
        candidate_name=None,
    )

    assert result.outcome is BrowserOutcome.DOWNLOADED
    assert result.filename == "CVAlejandracamachosaenz.docx"
    assert result.content_type == DOCX_CONTENT_TYPE
    assert result.data == docx.read_bytes()


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


def test_edge_configuration_uses_edge_channel_and_executable(tmp_path):
    context=FakeContext(FakeResponse(), FakePage())
    chromium=FakeChromium(context)
    calls=[]
    edge_cfg = AgentConfig(
        api_base_url="https://agent.test",
        browser_profile_dir=tmp_path / "profile-edge",
        browser_name="edge",
    )

    browser=IndeedBrowser(
        edge_cfg,
        playwright_factory=lambda: FakeManager(FakePlaywright(chromium)),
        browser_executable_resolver=lambda: r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        process_runner=lambda command: calls.append(command) or FakeProcess(),
    )
    browser.start()
    assert chromium.kwargs["channel"] == "msedge"
    browser.open_indeed()

    assert calls[0][0].endswith("msedge.exe")


def test_open_indeed_can_open_specific_safe_resume_url(tmp_path):
    calls=[]

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    browser=IndeedBrowser(
        cfg(tmp_path),
        browser_executable_resolver=lambda: r"C:\Program Files\Google\Chrome\Application\chrome.exe",
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
        browser_executable_resolver=lambda: r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        process_runner=run,
    )
    browser.open_indeed(url)

    assert calls[0][0][-1] == "https://employers.indeed.com/candidates"


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


def test_diagnostic_event_buffer_keeps_recent_download_event(tmp_path):
    browser = IndeedBrowser(cfg(tmp_path))
    browser._diagnostic_active = True

    for index in range(1300):
        browser._record_diagnostic_event(
            {"kind": "request", "url": f"https://indeed.test/{index}"}
        )
    browser._record_diagnostic_event(
        {
            "kind": "download",
            "url": "https://employers.indeed.com/candidates/resume",
            "suggested_filename": "candidate.pdf",
        }
    )

    assert len(browser._diagnostic_events) == 1200
    assert browser._diagnostic_events[-1]["kind"] == "download"
    assert browser._diagnostic_events[-1]["suggested_filename"] == "candidate.pdf"


def test_diagnostic_page_close_event_is_recorded(tmp_path):
    handlers = {}

    class EventPage(FakePage):
        def on(self, name, callback):
            handlers[name] = callback

    page = EventPage(url="https://employers.indeed.com/candidates/view")
    browser = IndeedBrowser(cfg(tmp_path))
    browser._diagnostic_active = True

    browser._attach_diagnostic_page(page)
    handlers["close"]()

    assert browser._diagnostic_events[-1]["kind"] == "page_closed"
    assert browser._diagnostic_events[-1]["url"] == "https://employers.indeed.com/candidates/view"


def test_safe_diagnostic_url_strips_query_and_fragment():
    assert _safe_diagnostic_url(
        "https://employers.indeed.com/resume/abc?token=secret#section"
    ) == "https://employers.indeed.com/resume/abc"


def test_safe_diagnostic_text_redacts_urls_and_secret_assignments():
    value = (
        "request https://employers.indeed.com/resume/abc?token=secret&sig=hidden "
        "authorization=topsecret"
    )
    safe = _safe_diagnostic_text(value)
    assert "secret" not in safe
    assert "hidden" not in safe
    assert "topsecret" not in safe
    assert "https://employers.indeed.com/resume/abc" in safe
    assert "authorization=[REDACTED]" in safe


def test_diagnostic_response_records_only_sanitized_metadata_and_pdf_signature(tmp_path):
    class Request:
        resource_type = "fetch"

    class Response:
        status = 200
        url = "https://employers.indeed.com/candidates/resume?token=secret&sig=hidden"
        request = Request()
        headers = {
            "content-type": "application/octet-stream",
            "content-disposition": 'attachment; filename="Candidate.pdf"; token=secret',
            "content-length": "9",
            "set-cookie": "must-not-be-recorded",
        }

        def body(self):
            return b"%PDF-test"

    browser = IndeedBrowser(cfg(tmp_path))
    browser._diagnostic_active = True
    browser._on_diagnostic_response(Response())

    assert len(browser._diagnostic_events) == 1
    event = browser._diagnostic_events[0]
    assert event["url"] == "https://employers.indeed.com/candidates/resume"
    assert event["starts_with_pdf"] is True
    assert event["body_size"] == 9
    assert "secret" not in json.dumps(event)
    assert "hidden" not in json.dumps(event)
    assert "must-not-be-recorded" not in json.dumps(event)


def test_stop_diagnostic_writes_privacy_manifest_and_page_snapshot(tmp_path):
    class DiagnosticPage(FakePage):
        def title(self):
            return "Candidate resume"

        def evaluate(self, script):
            if "document.contentType" in script:
                return {"contentType": "text/html", "readyState": "complete"}
            return "div"

        def is_closed(self):
            return False

        def screenshot(self, *, path, full_page):
            Path(path).write_bytes(b"png")

    page = DiagnosticPage(url="https://employers.indeed.com/candidates/resume?token=secret")
    context = FakeContext(FakeResponse(), page)
    browser = IndeedBrowser(cfg(tmp_path))
    browser._context = context
    browser._diagnostic_active = True
    browser._diagnostic_started_at = "2026-09-21T16:00:00+00:00"
    browser._diagnostic_events = [{"kind": "request", "url": "https://indeed.com/path"}]

    path = browser.stop_diagnostic()

    assert path is not None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["pages"][0]["url"] == "https://employers.indeed.com/candidates/resume"
    assert payload["pages"][0]["document_content_type"] == "text/html"
    assert payload["privacy"] == {
        "query_strings_persisted": False,
        "cookies_persisted": False,
        "authorization_headers_persisted": False,
        "response_bodies_persisted": False,
    }
    assert Path(payload["screenshot"]).is_file()


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
