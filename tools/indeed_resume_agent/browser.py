from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .config import AgentConfig


class BrowserOutcome(str, Enum):
    DOWNLOADED = "DOWNLOADED"
    NEEDS_HUMAN = "NEEDS_HUMAN"


@dataclass(frozen=True)
class BrowserResult:
    outcome: BrowserOutcome
    filename: str | None = None
    data: bytes | None = None
    human_code: str | None = None


class InvalidResumePdf(ValueError):
    def __init__(self, code: str):
        self.code = str(code)
        super().__init__(self.code)


def validate_pdf(data: bytes, *, max_bytes: int) -> None:
    payload = bytes(data or b"")
    if not payload.startswith(b"%PDF-"):
        raise InvalidResumePdf("RESUME_NOT_PDF")
    if len(payload) > int(max_bytes):
        raise InvalidResumePdf("RESUME_TOO_LARGE")


def normalize_pdf_filename(filename: str | None) -> str:
    raw = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    stem = Path(raw).stem.strip() if raw else "indeed-resume"
    safe = "".join(ch if ch.isalnum() or ch in " ._-" else "_" for ch in stem).strip()
    return f"{safe or 'indeed-resume'}.pdf"


def _default_playwright_factory():
    from playwright.sync_api import sync_playwright
    return sync_playwright()


_DOWNLOAD_NAME = re.compile(
    r"^(download|descargar)(\s+(cv|resume|curr[ií]culum))?$",
    re.IGNORECASE,
)
_CHALLENGE_MARKERS = (
    "sign in",
    "log in",
    "iniciar sesión",
    "iniciar sesion",
    "verification",
    "verificación",
    "verificacion",
    "captcha",
    "security challenge",
    "mfa",
    "two-step",
    "two factor",
)
_URL_CHALLENGE_MARKERS = ("/login", "/signin", "challenge", "captcha", "verify")


class IndeedBrowser:
    def __init__(self, config: AgentConfig, *, playwright_factory=None):
        self._config = config
        self._playwright_factory = playwright_factory or _default_playwright_factory
        self._playwright = None
        self._context = None

    def start(self) -> None:
        if self._context is not None:
            return
        self._config.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = self._playwright_factory().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._config.browser_profile_dir),
            channel="msedge",
            headless=False,
            accept_downloads=True,
        )

    def close(self) -> None:
        context, playwright = self._context, self._playwright
        self._context = None
        self._playwright = None
        if context is not None:
            context.close()
        if playwright is not None:
            playwright.stop()

    def _page(self):
        self.start()
        if self._context.pages:
            return self._context.pages[0]
        return self._context.new_page()

    def open_indeed(self) -> None:
        page = self._page()
        page.goto("https://www.indeed.com/", wait_until="domcontentloaded")
        bring_to_front = getattr(page, "bring_to_front", None)
        if callable(bring_to_front):
            bring_to_front()

    @staticmethod
    def _response_pdf(response) -> bytes | None:
        if response is None or int(getattr(response, "status", 0) or 0) != 200:
            return None
        headers = getattr(response, "headers", {}) or {}
        content_type = str(headers.get("content-type") or headers.get("Content-Type") or "").lower()
        if "application/pdf" not in content_type:
            return None
        body = response.body()
        return bytes(body or b"")

    @staticmethod
    def _requires_human(page) -> bool:
        url = str(getattr(page, "url", "") or "").casefold()
        if any(marker in url for marker in _URL_CHALLENGE_MARKERS):
            return True
        try:
            text = str(page.locator("body").inner_text(timeout=2000) or "").casefold()
        except Exception:
            text = ""
        return any(marker in text for marker in _CHALLENGE_MARKERS)

    @staticmethod
    def _known_download_control(page):
        for role in ("button", "link"):
            try:
                locator = page.get_by_role(role, name=_DOWNLOAD_NAME)
                if locator.count() > 0:
                    return locator.first
            except Exception:
                continue
        return None

    def fetch_resume(self, url: str) -> BrowserResult:
        self.start()
        resume_url = str(url or "").strip()
        if not resume_url.lower().startswith("https://"):
            return BrowserResult(BrowserOutcome.NEEDS_HUMAN, human_code="INDEED_UI_REQUIRES_REVIEW")

        try:
            response = self._context.request.get(resume_url, timeout=int(self._config.request_timeout_seconds * 1000))
            direct = self._response_pdf(response)
            if direct is not None:
                validate_pdf(direct, max_bytes=self._config.max_pdf_bytes)
                return BrowserResult(
                    BrowserOutcome.DOWNLOADED,
                    filename="indeed-resume.pdf",
                    data=direct,
                )
        except InvalidResumePdf:
            raise
        except Exception:
            pass

        page = self._page()
        navigation = page.goto(
            resume_url,
            wait_until="domcontentloaded",
            timeout=int(self._config.request_timeout_seconds * 1000),
        )
        navigated_pdf = self._response_pdf(navigation)
        if navigated_pdf is not None:
            validate_pdf(navigated_pdf, max_bytes=self._config.max_pdf_bytes)
            return BrowserResult(
                BrowserOutcome.DOWNLOADED,
                filename="indeed-resume.pdf",
                data=navigated_pdf,
            )

        if self._requires_human(page):
            return BrowserResult(BrowserOutcome.NEEDS_HUMAN, human_code="INDEED_AUTH_REQUIRED")

        control = self._known_download_control(page)
        if control is None:
            return BrowserResult(
                BrowserOutcome.NEEDS_HUMAN,
                human_code="INDEED_UI_REQUIRES_REVIEW",
            )

        with page.expect_download(timeout=int(self._config.request_timeout_seconds * 1000)) as download_info:
            control.click()
        download = download_info.value
        path = download.path()
        data = Path(path).read_bytes()
        validate_pdf(data, max_bytes=self._config.max_pdf_bytes)
        return BrowserResult(
            BrowserOutcome.DOWNLOADED,
            filename=normalize_pdf_filename(getattr(download, "suggested_filename", None)),
            data=data,
        )
