from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlsplit

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
    diagnostic_path: str | None = None


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


def _resolve_edge_executable() -> str:
    candidates: list[Path] = []
    discovered = shutil.which("msedge")
    if discovered:
        return discovered

    for key in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        root = str(os.environ.get(key, "")).strip()
        if not root:
            continue
        candidates.append(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe")

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("Microsoft Edge no está instalado o no pudo localizarse.")


_DOWNLOAD_NAME = re.compile(
    r"^(?:"
    r"(?:download|descargar)(?:\s+(?:cv|resume|curr[ií]culum|curriculum|hoja\s+de\s+vida))?"
    r"|(?:view|ver)\s+(?:cv|resume|curr[ií]culum|curriculum|hoja\s+de\s+vida)"
    r")$",
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




def _safe_diagnostic_url(raw_url: str | None) -> str:
    """Keep only scheme/host/path so signed query parameters are never persisted."""
    value = str(raw_url or "").strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
    except Exception:
        return ""
    if parsed.scheme.casefold() not in {"http", "https"}:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc}{parsed.path}"


class IndeedBrowser:
    def __init__(
        self,
        config: AgentConfig,
        *,
        playwright_factory=None,
        edge_executable_resolver=None,
        process_runner=None,
    ):
        self._config = config
        self._playwright_factory = playwright_factory or _default_playwright_factory
        self._edge_executable_resolver = edge_executable_resolver or _resolve_edge_executable
        self._process_runner = process_runner or subprocess.run
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
            chromium_sandbox=True,
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

    @staticmethod
    def _safe_manual_url(url: str | None) -> str:
        candidate = str(url or "").strip()
        if not candidate:
            return "https://www.indeed.com/"
        try:
            parsed = urlsplit(candidate)
        except Exception:
            return "https://www.indeed.com/"
        host = str(parsed.hostname or "").casefold()
        allowed = (
            host == "indeed.com"
            or host.endswith(".indeed.com")
            or host == "indeedemail.com"
            or host.endswith(".indeedemail.com")
        )
        if parsed.scheme.casefold() != "https" or not allowed:
            return "https://www.indeed.com/"
        return candidate

    def open_indeed(self, url: str | None = None) -> None:
        """Open Indeed in normal Edge, optionally at the blocked resume URL.

        The same dedicated user-data directory is reused later by Playwright, so
        cookies/session state survive without automating login, MFA, or CAPTCHA.
        """
        self.close()
        self._config.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        edge = self._edge_executable_resolver()
        command = [
            edge,
            f"--user-data-dir={self._config.browser_profile_dir}",
            "--new-window",
            "--no-first-run",
            "--no-default-browser-check",
            self._safe_manual_url(url),
        ]
        self._process_runner(command, check=False)

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

        # Indeed occasionally renders the resume action as an icon/link whose
        # accessible name differs from the visible text. Prefer trusted semantic
        # hints and direct PDF/download links before requiring human review.
        selectors = (
            'a[download]',
            'a[href*=".pdf"]',
            'a[href*="resume"]',
            'a[href*="cv"]',
            'button[aria-label*="download" i]',
            'button[aria-label*="descargar" i]',
            'a[aria-label*="download" i]',
            'a[aria-label*="descargar" i]',
        )
        for selector in selectors:
            try:
                locator = page.locator(selector)
                if locator.count() > 0:
                    return locator.first
            except Exception:
                continue
        return None


    def _write_ui_diagnostic(self, page) -> str | None:
        """Persist a local-only, redacted snapshot of the unexpected Indeed UI."""
        diagnostics_dir = self._config.browser_profile_dir.parent / "diagnostics"
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = diagnostics_dir / f"indeed-ui-review-{stamp}"
        json_path = base.with_suffix(".json")
        png_path = base.with_suffix(".png")

        try:
            title = str(page.title() or "")[:300]
        except Exception:
            title = ""

        controls: list[dict[str, str]] = []
        for selector, kind in (("button", "button"), ("a", "link")):
            try:
                items = page.locator(selector)
                count = min(int(items.count()), 80)
            except Exception:
                count = 0
                items = None
            for index in range(count):
                try:
                    node = items.nth(index)
                    if not node.is_visible():
                        continue
                    text = " ".join(str(node.inner_text(timeout=500) or "").split())[:200]
                    aria = str(node.get_attribute("aria-label") or "").strip()[:200]
                    href = (
                        _safe_diagnostic_url(node.get_attribute("href"))
                        if kind == "link"
                        else ""
                    )
                    controls.append(
                        {
                            "kind": kind,
                            "text": text,
                            "aria_label": aria,
                            "href": href,
                        }
                    )
                except Exception:
                    continue

        payload = {
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "url": _safe_diagnostic_url(getattr(page, "url", "")),
            "title": title,
            "controls": controls,
            "screenshot": str(png_path),
        }

        try:
            json_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            try:
                page.screenshot(path=str(png_path), full_page=True)
            except Exception:
                payload["screenshot"] = ""
                json_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            return str(json_path)
        except Exception:
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
            diagnostic_path = self._write_ui_diagnostic(page)
            return BrowserResult(
                BrowserOutcome.NEEDS_HUMAN,
                human_code="INDEED_UI_REQUIRES_REVIEW",
                diagnostic_path=diagnostic_path,
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
