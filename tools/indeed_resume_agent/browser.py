from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from email.header import decode_header, make_header

import psutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import unquote, urlsplit

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


class BrowserFetchStageError(RuntimeError):
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


def _manual_browser_process_exists(
    profile_dir: Path,
    *,
    process_name: str,
) -> bool:
    """Return True when the dedicated profile is owned by the selected browser."""
    target = os.path.normcase(os.path.normpath(str(profile_dir)))
    expected_process = str(process_name or "").casefold()
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            info = process.info
            if str(info.get("name") or "").casefold() != expected_process:
                continue
            args = [str(value) for value in (info.get("cmdline") or [])]
            if any(arg.startswith("--type=") for arg in args):
                continue
            for arg in args:
                if not arg.casefold().startswith("--user-data-dir="):
                    continue
                value = arg.split("=", 1)[1].strip().strip('"')
                candidate = os.path.normcase(os.path.normpath(value))
                if candidate == target:
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return False


def _resolve_browser_executable(browser_name: str) -> str:
    browser = str(browser_name or "").strip().casefold()
    if browser == "chrome":
        executable_name = "chrome.exe"
        shutil_names = ("chrome", "chrome.exe")
        relative_paths = (
            Path("Google") / "Chrome" / "Application" / executable_name,
        )
        display_name = "Google Chrome"
    elif browser == "edge":
        executable_name = "msedge.exe"
        shutil_names = ("msedge", "msedge.exe")
        relative_paths = (
            Path("Microsoft") / "Edge" / "Application" / executable_name,
        )
        display_name = "Microsoft Edge"
    else:
        raise RuntimeError(f"Navegador no soportado: {browser_name}")

    for candidate_name in shutil_names:
        discovered = shutil.which(candidate_name)
        if discovered:
            return discovered

    candidates: list[Path] = []
    for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = str(os.environ.get(key, "")).strip()
        if not root:
            continue
        for relative_path in relative_paths:
            candidates.append(Path(root) / relative_path)

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError(f"{display_name} no está instalado o no pudo localizarse.")


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
_INDEED_EMPLOYER_HOME = "https://employers.indeed.com/"
_INDEED_CANDIDATES_HOME = "https://employers.indeed.com/candidates"
_RESUME_DOWNLOAD_PATH = "/api/catws/resume/v2/download"
_FILENAME_STAR = re.compile(r"filename\*=UTF-8''([^;]+)", re.IGNORECASE)
_FILENAME_BASIC = re.compile(r'filename="?([^";]+)"?', re.IGNORECASE)




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


_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(token|auth|authorization|signature|sig|api[_-]?key|code|session|cookie)=([^\s&\"']+)"
)
_URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>]+")


def _safe_diagnostic_text(value: object, *, limit: int = 500) -> str:
    """Redact URL queries and common credential-like assignments from diagnostic text."""
    text = " ".join(str(value or "").split())
    text = _URL_IN_TEXT.sub(lambda match: _safe_diagnostic_url(match.group(0)), text)
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    return text[: max(0, int(limit))]


class IndeedBrowser:
    def __init__(
        self,
        config: AgentConfig,
        *,
        playwright_factory=None,
        browser_executable_resolver=None,
        process_runner=None,
        manual_process_probe=None,
    ):
        self._config = config
        self._browser_name = str(config.browser_name or "chrome").strip().casefold()
        if self._browser_name == "chrome":
            self._playwright_channel = "chrome"
            self._browser_process_name = "chrome.exe"
            self._browser_label = "Google Chrome"
        elif self._browser_name == "edge":
            self._playwright_channel = "msedge"
            self._browser_process_name = "msedge.exe"
            self._browser_label = "Microsoft Edge"
        else:
            raise ValueError(f"Navegador no soportado: {self._browser_name}")

        self._playwright_factory = playwright_factory or _default_playwright_factory
        self._browser_executable_resolver = (
            browser_executable_resolver
            or (lambda: _resolve_browser_executable(self._browser_name))
        )
        self._process_runner = process_runner or subprocess.Popen
        self._manual_process_probe = manual_process_probe or (
            lambda profile_dir: _manual_browser_process_exists(
                profile_dir,
                process_name=self._browser_process_name,
            )
        )
        self._manual_process = None
        self._playwright = None
        self._context = None
        self._diagnostic_active = False
        self._diagnostic_started_at: str | None = None
        self._diagnostic_events: list[dict] = []
        self._diagnostic_context_hooked = False
        self._diagnostic_page_ids: set[int] = set()
        self._diagnostic_anchor_page_id: int | None = None
        self._last_diagnostic_path: str | None = None

    @property
    def browser_label(self) -> str:
        return self._browser_label

    @property
    def diagnostic_active(self) -> bool:
        return self._diagnostic_active

    @property
    def last_diagnostic_path(self) -> str | None:
        return self._last_diagnostic_path

    @property
    def manual_session_open(self) -> bool:
        # When Playwright owns the persistent profile, its Chrome root process
        # has the same --user-data-dir as the manual browser. Process probing
        # must not classify our own automated Chrome as a manual session or the
        # UI will block every subsequent queue attempt with MANUAL_BROWSER_OPEN.
        if self._context is not None:
            return False

        process = self._manual_process
        if process is not None:
            poll = getattr(process, "poll", None)
            if callable(poll):
                try:
                    if poll() is None:
                        return True
                except Exception:
                    return True

        try:
            running = bool(self._manual_process_probe(self._config.browser_profile_dir))
        except Exception:
            running = False

        if not running:
            self._manual_process = None
        return running

    def _context_has_live_page(self) -> bool:
        context = self._context
        if context is None:
            return False
        try:
            pages = list(getattr(context, "pages", []) or [])
        except Exception:
            return False
        for page in pages:
            try:
                if hasattr(page, "is_closed") and page.is_closed():
                    continue
                return True
            except Exception:
                return True
        return False

    def _discard_stale_context(self) -> None:
        context, playwright = self._context, self._playwright
        self._context = None
        self._playwright = None
        self._diagnostic_context_hooked = False
        self._diagnostic_page_ids.clear()
        self._diagnostic_anchor_page_id = None
        try:
            if context is not None:
                context.close()
        except Exception:
            pass
        try:
            if playwright is not None:
                playwright.stop()
        except Exception:
            pass

    def _wait_for_manual_session_close(self, timeout_seconds: float = 2.5) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while True:
            if not self.manual_session_open:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    def start(self) -> None:
        if self._context is not None:
            if self._context_has_live_page():
                return
            # A user can close the Playwright Chrome window directly. The
            # BrowserContext object then remains referenced in the agent even
            # though the underlying browser is gone. Drop that stale context so
            # the next Diagnostic mode click relaunches Chrome cleanly.
            self._discard_stale_context()

        if self.manual_session_open:
            raise RuntimeError("INDEED_MANUAL_BROWSER_OPEN")
        self._config.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = self._playwright_factory().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._config.browser_profile_dir),
            channel=self._playwright_channel,
            headless=False,
            accept_downloads=True,
            chromium_sandbox=True,
        )

    def close(self) -> None:
        if self._diagnostic_active:
            try:
                self.stop_diagnostic()
            except Exception:
                self._diagnostic_active = False
        context, playwright = self._context, self._playwright
        self._context = None
        self._playwright = None
        self._diagnostic_context_hooked = False
        self._diagnostic_page_ids.clear()
        self._diagnostic_anchor_page_id = None
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
            return _INDEED_EMPLOYER_HOME
        try:
            parsed = urlsplit(candidate)
        except Exception:
            return _INDEED_EMPLOYER_HOME
        host = str(parsed.hostname or "").casefold()
        allowed = (
            host == "indeed.com"
            or host.endswith(".indeed.com")
            or host == "indeedemail.com"
            or host.endswith(".indeedemail.com")
        )
        if parsed.scheme.casefold() != "https" or not allowed:
            return _INDEED_EMPLOYER_HOME
        return candidate

    def open_indeed(self, url: str | None = None) -> None:
        """Open Indeed in the configured normal browser with its dedicated profile.

        The same dedicated user-data directory is reused later by Playwright, so
        cookies/session state survive without automating login, MFA, or CAPTCHA.
        """
        if self.manual_session_open:
            return
        self.close()
        self._config.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        executable = self._browser_executable_resolver()
        command = [
            executable,
            f"--user-data-dir={self._config.browser_profile_dir}",
            "--new-window",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-mode",
            self._safe_manual_url(url),
        ]
        self._manual_process = self._process_runner(command)

    @staticmethod
    def _response_pdf(response, *, probe_body: bool = True) -> bytes | None:
        if response is None or int(getattr(response, "status", 0) or 0) != 200:
            return None

        headers = getattr(response, "headers", {}) or {}
        content_type = str(
            headers.get("content-type") or headers.get("Content-Type") or ""
        ).lower()
        content_disposition = str(
            headers.get("content-disposition")
            or headers.get("Content-Disposition")
            or ""
        ).lower()
        response_url = str(getattr(response, "url", "") or "")

        # Do not ask Playwright for the body of ordinary HTML/page responses.
        # Chromium can discard navigation bodies once the document is committed,
        # which makes response.body() raise even though navigation succeeded.
        # Only probe the body when response metadata plausibly represents a file.
        plausible_pdf = (
            "application/pdf" in content_type
            or "application/octet-stream" in content_type
            or "binary/octet-stream" in content_type
            or "attachment" in content_disposition
            or response_url.casefold().endswith(".pdf")
        )
        if not plausible_pdf and not probe_body:
            return None

        body = bytes(response.body() or b"")

        # Indeed's resume endpoint can deliver the file with a generic binary
        # content type. Trust the PDF signature first and keep the declared PDF
        # MIME type as a secondary signal so malformed PDFs still fail
        # validation explicitly.
        if body.startswith(b"%PDF-"):
            return body
        if "application/pdf" in content_type:
            return body
        return None

    @staticmethod
    def _is_resume_download_response(response) -> bool:
        try:
            parsed = urlsplit(str(getattr(response, "url", "") or ""))
        except Exception:
            return False
        host = str(parsed.hostname or "").casefold()
        return (
            host == "employers.indeed.com"
            and parsed.path == _RESUME_DOWNLOAD_PATH
            and int(getattr(response, "status", 0) or 0) == 200
        )

    @staticmethod
    def _response_filename(response) -> str:
        headers = getattr(response, "headers", {}) or {}
        disposition = str(
            headers.get("content-disposition")
            or headers.get("Content-Disposition")
            or ""
        )
        candidate = ""
        match = _FILENAME_STAR.search(disposition)
        if match:
            candidate = unquote(match.group(1))
        else:
            match = _FILENAME_BASIC.search(disposition)
            if match:
                candidate = match.group(1).strip()
                try:
                    candidate = str(make_header(decode_header(candidate)))
                except Exception:
                    pass
        return normalize_pdf_filename(candidate or "indeed-resume.pdf")

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
    def _is_generic_recruiting_landing(page) -> bool:
        try:
            parsed = urlsplit(str(getattr(page, "url", "") or ""))
        except Exception:
            return False
        host = str(parsed.hostname or "").casefold()
        path = str(parsed.path or "").rstrip("/")
        return host == "resumes.indeed.com" and path in {"", "/"}


    def _wait_for_download_control(self, page):
        # Indeed Employers is a client-rendered SPA. domcontentloaded only
        # guarantees the shell document exists; the candidate view and its
        # Descargar CV action can appear several seconds later.
        interval_ms = 500
        attempts = max(
            1,
            min(
                30,
                int(max(1.0, float(self._config.request_timeout_seconds)) * 1000)
                // interval_ms,
            ),
        )
        for _ in range(attempts):
            control = self._known_download_control(page)
            if control is not None:
                return control

            try:
                url = str(getattr(page, "url", "") or "").casefold()
                if any(marker in url for marker in _URL_CHALLENGE_MARKERS):
                    return None
                if hasattr(page, "is_closed") and page.is_closed():
                    return None
            except Exception:
                return None

            try:
                page.wait_for_timeout(interval_ms)
            except Exception:
                time.sleep(interval_ms / 1000.0)

        return self._known_download_control(page)

    @staticmethod
    def _candidate_navigation_control(page):
        navigation_name = re.compile(
            r"^(?:candidatos|candidates|ver candidatos|view candidates|"
            r"administrar candidatos|manage candidates)$",
            re.IGNORECASE,
        )
        for role in ("link", "button"):
            try:
                locator = page.get_by_role(role, name=navigation_name)
                if locator.count() > 0:
                    return locator.first
            except Exception:
                continue

        for selector in (
            '[aria-label="Candidatos" i]',
            '[aria-label="Candidates" i]',
            '[title="Candidatos" i]',
            '[title="Candidates" i]',
            'a[href*="candidate" i]',
        ):
            try:
                locator = page.locator(selector)
                if locator.count() > 0:
                    return locator.first
            except Exception:
                continue
        return None

    def _open_candidates_workspace(self, page) -> bool:
        control = self._candidate_navigation_control(page)
        if control is not None:
            try:
                control.click()
                page.wait_for_timeout(750)
                if not self._is_generic_recruiting_landing(page):
                    return True
            except Exception:
                pass

        # Keep the old direct URL as a final fallback. Some accounts expose the
        # classic candidates workspace here, while others redirect it back to
        # Smart Recruiting.
        try:
            page.goto(
                _INDEED_CANDIDATES_HOME,
                wait_until="domcontentloaded",
                timeout=int(self._config.request_timeout_seconds * 1000),
            )
            return not self._is_generic_recruiting_landing(page)
        except Exception:
            return False

    @staticmethod
    def _candidate_search_box(page):
        try:
            by_role = page.get_by_role(
                "textbox",
                name=re.compile(r"(?:buscar|search).*candidat", re.IGNORECASE),
            )
            if by_role.count() > 0:
                return by_role.first
        except Exception:
            pass

        for selector in (
            'input[placeholder*="candidat" i]',
            'input[placeholder*="buscar" i]',
            'input[placeholder*="search" i]',
        ):
            try:
                located = page.locator(selector)
                if located.count() > 0:
                    return located.first
            except Exception:
                continue
        return None

    @staticmethod
    def _candidate_search_trigger(page):
        for role in ("button", "link"):
            try:
                located = page.get_by_role(
                    role,
                    name=re.compile(
                        r"^(?:buscar|search|buscar candidatos|search candidates)$",
                        re.IGNORECASE,
                    ),
                )
                if located.count() > 0:
                    return located.first
            except Exception:
                continue
        for selector in (
            '[aria-label*="buscar" i]',
            '[aria-label*="search" i]',
            '[title*="buscar" i]',
            '[title*="search" i]',
        ):
            try:
                located = page.locator(selector)
                if located.count() > 0:
                    return located.first
            except Exception:
                continue
        return None

    def _open_candidate_from_list(self, page, candidate_name: str):
        name = " ".join(str(candidate_name or "").split()).strip()
        if not name:
            return None

        if not self._open_candidates_workspace(page):
            return None

        if self._requires_human(page):
            return None

        exact_name = re.compile(rf"^\s*{re.escape(name)}\s*$", re.IGNORECASE)
        interval_ms = 500
        attempts = max(
            1,
            min(
                30,
                int(max(1.0, float(self._config.request_timeout_seconds)) * 1000)
                // interval_ms,
            ),
        )
        search_filled = False
        search_triggered = False

        for _ in range(attempts):
            try:
                candidate = page.get_by_text(exact_name)
                if candidate.count() > 0:
                    candidate.first.click()
                    return self._wait_for_download_control(page)
            except Exception:
                pass

            if not search_filled:
                search_box = self._candidate_search_box(page)
                if search_box is None and not search_triggered:
                    trigger = self._candidate_search_trigger(page)
                    if trigger is not None:
                        try:
                            trigger.click()
                            search_triggered = True
                            page.wait_for_timeout(500)
                        except Exception:
                            pass
                    search_box = self._candidate_search_box(page)

                if search_box is not None:
                    try:
                        search_box.fill(name)
                        search_filled = True
                    except Exception:
                        pass

            try:
                page.wait_for_timeout(interval_ms)
            except Exception:
                time.sleep(interval_ms / 1000.0)

        return None

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


    def _record_diagnostic_event(self, event: dict) -> None:
        if not self._diagnostic_active:
            return
        payload = dict(event)
        payload["captured_at_utc"] = datetime.now(timezone.utc).isoformat()

        # Keep a rolling window instead of stopping after the initial page-load
        # burst. Indeed can emit hundreds of analytics/static requests before
        # the user clicks "Descargar CV"; the useful download/close event must
        # remain observable even when the page is noisy.
        max_events = 1200
        if len(self._diagnostic_events) >= max_events:
            del self._diagnostic_events[: len(self._diagnostic_events) - max_events + 1]
        self._diagnostic_events.append(payload)

    def _on_diagnostic_request(self, request) -> None:
        try:
            self._record_diagnostic_event(
                {
                    "kind": "request",
                    "method": str(getattr(request, "method", "") or "")[:16],
                    "resource_type": str(getattr(request, "resource_type", "") or "")[:40],
                    "url": _safe_diagnostic_url(getattr(request, "url", "")),
                }
            )
        except Exception:
            pass

    def _on_diagnostic_response(self, response) -> None:
        try:
            request = getattr(response, "request", None)
            headers = getattr(response, "headers", {}) or {}
            content_type = str(
                headers.get("content-type") or headers.get("Content-Type") or ""
            )[:200]
            content_disposition = _safe_diagnostic_text(
                headers.get("content-disposition")
                or headers.get("Content-Disposition")
                or "",
                limit=300,
            )
            safe_url = _safe_diagnostic_url(getattr(response, "url", ""))
            event = {
                "kind": "response",
                "status": int(getattr(response, "status", 0) or 0),
                "resource_type": str(
                    getattr(request, "resource_type", "") or ""
                )[:40],
                "url": safe_url,
                "content_type": content_type,
                "content_disposition": content_disposition,
                "content_length": str(
                    headers.get("content-length")
                    or headers.get("Content-Length")
                    or ""
                )[:40],
            }

            relevant = any(
                marker in safe_url.casefold()
                for marker in ("resume", "candidate", "download", ".pdf")
            ) or any(
                marker in content_type.casefold()
                for marker in ("pdf", "octet-stream")
            )
            if relevant and event["status"] < 400:
                try:
                    body = bytes(response.body() or b"")
                    event["body_size"] = len(body)
                    event["starts_with_pdf"] = body.startswith(b"%PDF-")
                    event["first_bytes_hex"] = body[:24].hex()
                except Exception as exc:
                    event["body_probe_error"] = _safe_diagnostic_text(exc, limit=160)
            self._record_diagnostic_event(event)
        except Exception:
            pass

    def _attach_diagnostic_page(self, page) -> None:
        page_id = id(page)
        if page_id in self._diagnostic_page_ids:
            return
        self._diagnostic_page_ids.add(page_id)

        try:
            page.on(
                "download",
                lambda download: self._record_diagnostic_event(
                    {
                        "kind": "download",
                        "url": _safe_diagnostic_url(getattr(download, "url", "")),
                        "suggested_filename": _safe_diagnostic_text(
                            getattr(download, "suggested_filename", ""),
                            limit=220,
                        ),
                    }
                ),
            )
        except Exception:
            pass

        try:
            page.on(
                "console",
                lambda message: (
                    self._record_diagnostic_event(
                        {
                            "kind": "console",
                            "level": str(getattr(message, "type", "") or "")[:20],
                            "text": _safe_diagnostic_text(
                                getattr(message, "text", ""),
                                limit=500,
                            ),
                        }
                    )
                    if str(getattr(message, "type", "") or "").casefold()
                    in {"warning", "error"}
                    else None
                ),
            )
        except Exception:
            pass

        try:
            page.on(
                "pageerror",
                lambda error: self._record_diagnostic_event(
                    {
                        "kind": "pageerror",
                        "text": _safe_diagnostic_text(error, limit=500),
                    }
                ),
            )
        except Exception:
            pass

        try:
            page.on(
                "close",
                lambda: self._record_diagnostic_event(
                    {
                        "kind": "page_closed",
                        "url": _safe_diagnostic_url(getattr(page, "url", "")),
                    }
                ),
            )
        except Exception:
            pass

        try:
            page.on(
                "crash",
                lambda: self._record_diagnostic_event(
                    {
                        "kind": "page_crashed",
                        "url": _safe_diagnostic_url(getattr(page, "url", "")),
                    }
                ),
            )
        except Exception:
            pass

    def _attach_diagnostic_context(self) -> None:
        if self._context is None:
            return
        if not self._diagnostic_context_hooked:
            try:
                self._context.on("request", self._on_diagnostic_request)
                self._context.on("response", self._on_diagnostic_response)
                self._context.on("page", self._attach_diagnostic_page)
                self._context.on(
                    "close",
                    lambda: self._record_diagnostic_event(
                        {"kind": "browser_context_closed"}
                    ),
                )
                self._diagnostic_context_hooked = True
            except Exception:
                pass
        for page in list(getattr(self._context, "pages", []) or []):
            self._attach_diagnostic_page(page)

    def start_diagnostic(self, url: str | None = None) -> None:
        """Open a visible Playwright-controlled Indeed session and capture only sanitized metadata."""
        # Chrome can take a moment to release the dedicated profile after the
        # user closes the manual window. Tolerate that normal shutdown race
        # instead of making the first Diagnostic mode click appear to do nothing.
        if self.manual_session_open and not self._wait_for_manual_session_close():
            raise RuntimeError("INDEED_MANUAL_BROWSER_OPEN")
        self.start()
        self._diagnostic_events = []
        self._diagnostic_started_at = datetime.now(timezone.utc).isoformat()
        self._last_diagnostic_path = None
        self._diagnostic_active = True

        # Use the first browser page as the real Indeed page. Creating the
        # anchor first proved unreliable on Windows/Chrome because Chrome could
        # coalesce the initial blank page. We materialize Indeed first, then
        # create and focus a second explicit anchor page.
        page = self._page()
        self._attach_diagnostic_context()
        self._attach_diagnostic_page(page)

        target = self._safe_manual_url(url)
        try:
            page.goto(
                target,
                wait_until="domcontentloaded",
                timeout=int(self._config.request_timeout_seconds * 1000),
            )
        except Exception as exc:
            self._record_diagnostic_event(
                {
                    "kind": "navigation_error",
                    "url": _safe_diagnostic_url(target),
                    "text": _safe_diagnostic_text(exc, limit=300),
                }
            )

        # Google/Indeed authentication must happen in the normal manual browser,
        # never inside the Playwright-controlled diagnostic window. Google can
        # reject automated browser contexts as "not secure".
        if self._requires_human(page):
            self._diagnostic_active = False
            self.close()
            raise RuntimeError("INDEED_MANUAL_LOGIN_REQUIRED")

        # Create the keep-alive page only after Indeed is loaded. Bring the
        # anchor to front once, then return focus to Indeed; this forces Chrome
        # to materialize the second page instead of silently reusing the startup
        # blank page.
        anchor = self._context.new_page()
        self._diagnostic_anchor_page_id = id(anchor)
        self._attach_diagnostic_page(anchor)
        try:
            anchor.set_content(
                "<title>ASIATI — KEEP OPEN</title>"
                "<body style='font-family:sans-serif;padding:28px'>"
                "<h2>ASIATI Resume Agent</h2>"
                "<p>Diagnostic keep-alive page. Do not close this tab.</p>"
                "</body>"
            )
            if hasattr(anchor, "bring_to_front"):
                anchor.bring_to_front()
            if hasattr(anchor, "wait_for_timeout"):
                anchor.wait_for_timeout(250)
            if hasattr(page, "bring_to_front"):
                page.bring_to_front()
        except Exception:
            pass

        open_pages = [
            candidate
            for candidate in list(getattr(self._context, "pages", []) or [])
            if not (hasattr(candidate, "is_closed") and candidate.is_closed())
        ]
        self._record_diagnostic_event(
            {
                "kind": "diagnostic_pages_ready",
                "page_count": len(open_pages),
                "anchor_created": any(
                    id(candidate) == self._diagnostic_anchor_page_id
                    for candidate in open_pages
                ),
            }
        )
        if len(open_pages) < 2:
            self._diagnostic_active = False
            self.close()
            raise RuntimeError("INDEED_DIAGNOSTIC_ANCHOR_FAILED")

    def poll_diagnostic(self) -> None:
        """Pump Playwright events while the user interacts with the visible diagnostic browser."""
        if not self._diagnostic_active or self._context is None:
            return
        self._attach_diagnostic_context()
        pages = list(getattr(self._context, "pages", []) or [])
        for page in pages:
            try:
                if id(page) == self._diagnostic_anchor_page_id:
                    continue
                if hasattr(page, "is_closed") and page.is_closed():
                    continue
                page.wait_for_timeout(100)
                return
            except Exception:
                continue

        # If the candidate tab closed itself after the download, keep pumping
        # Playwright from the anchor so download/close events can still flush.
        for page in pages:
            try:
                if id(page) != self._diagnostic_anchor_page_id:
                    continue
                if hasattr(page, "is_closed") and page.is_closed():
                    continue
                page.wait_for_timeout(100)
                return
            except Exception:
                continue

    @staticmethod
    def _diagnostic_controls(page) -> list[dict[str, str]]:
        controls: list[dict[str, str]] = []
        try:
            items = page.locator('button, a, [role="button"], iframe, embed, object')
            count = min(int(items.count()), 120)
        except Exception:
            return controls

        for index in range(count):
            try:
                node = items.nth(index)
                tag = str(node.evaluate("el => el.tagName.toLowerCase()") or "")[:30]
                if tag not in {"iframe", "embed", "object"} and not node.is_visible():
                    continue
                href = (
                    node.get_attribute("href")
                    or node.get_attribute("src")
                    or node.get_attribute("data")
                    or ""
                )
                controls.append(
                    {
                        "tag": tag,
                        "role": str(node.get_attribute("role") or "")[:80],
                        "text": _safe_diagnostic_text(
                            node.inner_text(timeout=500) if tag not in {"iframe", "embed", "object"} else "",
                            limit=220,
                        ),
                        "aria_label": _safe_diagnostic_text(
                            node.get_attribute("aria-label") or "",
                            limit=220,
                        ),
                        "data_testid": _safe_diagnostic_text(
                            node.get_attribute("data-testid") or "",
                            limit=160,
                        ),
                        "target": _safe_diagnostic_url(href),
                    }
                )
            except Exception:
                continue
        return controls

    def stop_diagnostic(self) -> str | None:
        """Persist a local sanitized JSON/screenshot bundle and stop capturing."""
        if not self._diagnostic_active:
            return self._last_diagnostic_path

        self._diagnostic_active = False
        diagnostics_dir = self._config.browser_profile_dir.parent / "diagnostics"
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = diagnostics_dir / f"indeed-flow-diagnostic-{stamp}"
        json_path = base.with_suffix(".json")
        screenshot_path = base.with_suffix(".png")

        pages_payload: list[dict] = []
        screenshot_saved = False
        pages = list(getattr(self._context, "pages", []) or []) if self._context is not None else []
        for page in pages:
            try:
                if id(page) == self._diagnostic_anchor_page_id:
                    continue
                if hasattr(page, "is_closed") and page.is_closed():
                    continue
                try:
                    title = _safe_diagnostic_text(page.title(), limit=300)
                except Exception:
                    title = ""
                try:
                    document_info = page.evaluate(
                        "() => ({contentType: document.contentType || '', readyState: document.readyState || ''})"
                    ) or {}
                except Exception:
                    document_info = {}
                pages_payload.append(
                    {
                        "url": _safe_diagnostic_url(getattr(page, "url", "")),
                        "title": title,
                        "document_content_type": str(document_info.get("contentType") or "")[:160],
                        "ready_state": str(document_info.get("readyState") or "")[:40],
                        "controls": self._diagnostic_controls(page),
                    }
                )
                if not screenshot_saved:
                    try:
                        page.screenshot(path=str(screenshot_path), full_page=True)
                        screenshot_saved = True
                    except Exception:
                        pass
            except Exception:
                continue

        payload = {
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "started_at_utc": self._diagnostic_started_at,
            "events": list(self._diagnostic_events),
            "pages": pages_payload,
            "screenshot": str(screenshot_path) if screenshot_saved else "",
            "privacy": {
                "query_strings_persisted": False,
                "cookies_persisted": False,
                "authorization_headers_persisted": False,
                "response_bodies_persisted": False,
            },
        }
        try:
            json_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._last_diagnostic_path = str(json_path)
            return self._last_diagnostic_path
        except Exception:
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

    def fetch_resume(
        self,
        url: str,
        *,
        candidate_name: str | None = None,
    ) -> BrowserResult:
        try:
            self.start()
        except Exception as exc:
            raise BrowserFetchStageError("RESUME_BROWSER_START_FAILED") from exc
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

        try:
            page = self._page()
        except Exception as exc:
            raise BrowserFetchStageError("RESUME_BROWSER_PAGE_FAILED") from exc

        try:
            navigation = page.goto(
                resume_url,
                wait_until="domcontentloaded",
                timeout=int(self._config.request_timeout_seconds * 1000),
            )
        except Exception as exc:
            raise BrowserFetchStageError("RESUME_BROWSER_NAVIGATION_FAILED") from exc

        try:
            navigated_pdf = self._response_pdf(navigation, probe_body=False)
        except InvalidResumePdf:
            raise
        except Exception as exc:
            raise BrowserFetchStageError(
                "RESUME_BROWSER_NAVIGATION_RESPONSE_FAILED"
            ) from exc
        if navigated_pdf is not None:
            validate_pdf(navigated_pdf, max_bytes=self._config.max_pdf_bytes)
            return BrowserResult(
                BrowserOutcome.DOWNLOADED,
                filename="indeed-resume.pdf",
                data=navigated_pdf,
            )

        generic_landing = self._is_generic_recruiting_landing(page)
        control = None if generic_landing else self._wait_for_download_control(page)

        if self._requires_human(page):
            return BrowserResult(BrowserOutcome.NEEDS_HUMAN, human_code="INDEED_AUTH_REQUIRED")

        fallback_attempted = False
        if (generic_landing or control is None) and str(candidate_name or "").strip():
            fallback_attempted = True
            control = self._open_candidate_from_list(page, str(candidate_name))

        if self._requires_human(page):
            return BrowserResult(BrowserOutcome.NEEDS_HUMAN, human_code="INDEED_AUTH_REQUIRED")

        if control is None:
            diagnostic_path = self._write_ui_diagnostic(page)
            return BrowserResult(
                BrowserOutcome.NEEDS_HUMAN,
                human_code=(
                    "INDEED_CANDIDATE_NOT_FOUND"
                    if fallback_attempted
                    else "INDEED_UI_REQUIRES_REVIEW"
                ),
                diagnostic_path=diagnostic_path,
            )

        captured_pdf: dict[str, object] = {}

        def capture_resume_response(response) -> None:
            if not self._is_resume_download_response(response):
                return
            try:
                data = self._response_pdf(response)
                if data is None:
                    return
                validate_pdf(data, max_bytes=self._config.max_pdf_bytes)
                captured_pdf["data"] = data
                captured_pdf["filename"] = self._response_filename(response)
            except InvalidResumePdf:
                captured_pdf["invalid_pdf"] = True
            except Exception:
                pass

        try:
            page.on("response", capture_resume_response)
        except Exception:
            pass

        try:
            with page.expect_download(
                timeout=int(self._config.request_timeout_seconds * 1000)
            ) as download_info:
                control.click()

            if captured_pdf.get("invalid_pdf"):
                raise InvalidResumePdf("RESUME_NOT_PDF")

            if isinstance(captured_pdf.get("data"), (bytes, bytearray)):
                return BrowserResult(
                    BrowserOutcome.DOWNLOADED,
                    filename=str(captured_pdf.get("filename") or "indeed-resume.pdf"),
                    data=bytes(captured_pdf["data"]),
                )

            download = download_info.value
            path = download.path()
            data = Path(path).read_bytes()
            validate_pdf(data, max_bytes=self._config.max_pdf_bytes)
            return BrowserResult(
                BrowserOutcome.DOWNLOADED,
                filename=normalize_pdf_filename(
                    getattr(download, "suggested_filename", None)
                ),
                data=data,
            )
        except InvalidResumePdf:
            raise
        except Exception:
            # Indeed currently returns the PDF response before closing the
            # candidate tab/browser context. If the browser vanishes before
            # Playwright can finish the Download object, prefer the already
            # captured authenticated PDF response.
            if captured_pdf.get("invalid_pdf"):
                raise InvalidResumePdf("RESUME_NOT_PDF")
            if isinstance(captured_pdf.get("data"), (bytes, bytearray)):
                return BrowserResult(
                    BrowserOutcome.DOWNLOADED,
                    filename=str(captured_pdf.get("filename") or "indeed-resume.pdf"),
                    data=bytes(captured_pdf["data"]),
                )

            diagnostic_path = self._write_ui_diagnostic(page)
            return BrowserResult(
                BrowserOutcome.NEEDS_HUMAN,
                human_code="INDEED_DOWNLOAD_ACTION_REQUIRES_REVIEW",
                diagnostic_path=diagnostic_path,
            )
        finally:
            try:
                page.off("response", capture_resume_response)
            except Exception:
                pass
