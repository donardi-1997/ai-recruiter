from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import time
import unicodedata
import zipfile
from datetime import datetime, timezone
from email.header import decode_header, make_header

import psutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import quote_plus, unquote, urlsplit

from .config import AgentConfig


class BrowserOutcome(str, Enum):
    DOWNLOADED = "DOWNLOADED"
    NEEDS_HUMAN = "NEEDS_HUMAN"


@dataclass(frozen=True)
class BrowserResult:
    outcome: BrowserOutcome
    filename: str | None = None
    data: bytes | None = None
    content_type: str | None = None
    human_code: str | None = None
    diagnostic_path: str | None = None


class InvalidResumeDocument(ValueError):
    def __init__(self, code: str):
        self.code = str(code)
        super().__init__(self.code)


# Backwards-compatible name for callers/tests that imported the former PDF-only
# exception. The agent now accepts PDF and DOCX.
InvalidResumePdf = InvalidResumeDocument


class BrowserFetchStageError(RuntimeError):
    def __init__(self, code: str):
        self.code = str(code)
        super().__init__(self.code)


PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_GENERIC_BINARY_CONTENT_TYPES = {
    "",
    "application/octet-stream",
    "binary/octet-stream",
}


def _is_docx(payload: bytes) -> bool:
    if not payload.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError):
        return False
    return "[Content_Types].xml" in names and "word/document.xml" in names


def validate_resume_document(
    data: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
    max_bytes: int,
) -> str:
    """Validate a supported resume and return its canonical MIME type."""
    payload = bytes(data or b"")
    if len(payload) > int(max_bytes):
        raise InvalidResumeDocument("RESUME_TOO_LARGE")

    declared = str(content_type or "").split(";", 1)[0].strip().casefold()
    suffix = Path(str(filename or "")).suffix.casefold()

    if payload.startswith(b"%PDF-"):
        return PDF_CONTENT_TYPE
    if _is_docx(payload):
        return DOCX_CONTENT_TYPE

    if declared == PDF_CONTENT_TYPE or suffix == ".pdf":
        raise InvalidResumeDocument("RESUME_NOT_PDF")
    if declared == DOCX_CONTENT_TYPE or suffix == ".docx":
        raise InvalidResumeDocument("RESUME_NOT_DOCX")
    raise InvalidResumeDocument("RESUME_UNSUPPORTED_FORMAT")


def validate_pdf(data: bytes, *, max_bytes: int) -> None:
    """Compatibility wrapper for legacy PDF-only callers."""
    detected = validate_resume_document(
        data,
        filename="resume.pdf",
        content_type=PDF_CONTENT_TYPE,
        max_bytes=max_bytes,
    )
    if detected != PDF_CONTENT_TYPE:
        raise InvalidResumeDocument("RESUME_NOT_PDF")


def normalize_resume_filename(
    filename: str | None,
    *,
    content_type: str,
) -> str:
    raw = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    stem = Path(raw).stem.strip() if raw else "indeed-resume"
    safe = "".join(ch if ch.isalnum() or ch in " ._-" else "_" for ch in stem).strip()
    extension = ".docx" if content_type == DOCX_CONTENT_TYPE else ".pdf"
    return f"{safe or 'indeed-resume'}{extension}"


def normalize_pdf_filename(filename: str | None) -> str:
    return normalize_resume_filename(filename, content_type=PDF_CONTENT_TYPE)


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
            return _INDEED_CANDIDATES_HOME
        try:
            parsed = urlsplit(candidate)
        except Exception:
            return _INDEED_CANDIDATES_HOME
        host = str(parsed.hostname or "").casefold()
        allowed = (
            host == "indeed.com"
            or host.endswith(".indeed.com")
            or host == "indeedemail.com"
            or host.endswith(".indeedemail.com")
        )
        if parsed.scheme.casefold() != "https" or not allowed:
            return _INDEED_CANDIDATES_HOME
        return candidate

    def open_indeed(self, url: str | None = None) -> None:
        """Open Indeed in the configured normal browser with its dedicated profile.

        The same dedicated user-data directory is reused later by Playwright, so
        cookies/session state survive without automating login, MFA, or CAPTCHA.
        """
        # Always issue a normal Chrome launch. If Chrome already owns this
        # dedicated profile, Chrome routes the command to the existing process
        # and opens a fresh window. Returning early here made the UI button look
        # broken whenever a background Chrome process survived after its window
        # was closed.
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
    def _response_document(response, *, probe_body: bool = True):
        if response is None or int(getattr(response, "status", 0) or 0) != 200:
            return None

        headers = getattr(response, "headers", {}) or {}
        content_type = str(
            headers.get("content-type") or headers.get("Content-Type") or ""
        ).split(";", 1)[0].strip().casefold()
        content_disposition = str(
            headers.get("content-disposition")
            or headers.get("Content-Disposition")
            or ""
        )
        response_url = str(getattr(response, "url", "") or "")
        disposition_lower = content_disposition.casefold()

        plausible_document = (
            content_type in {PDF_CONTENT_TYPE, DOCX_CONTENT_TYPE}
            or content_type in _GENERIC_BINARY_CONTENT_TYPES
            or "attachment" in disposition_lower
            or response_url.casefold().endswith((".pdf", ".docx"))
        )
        if not plausible_document and not probe_body:
            return None

        body = bytes(response.body() or b"")
        filename = IndeedBrowser._response_filename_raw(response)
        try:
            canonical_type = validate_resume_document(
                body,
                filename=filename,
                content_type=content_type,
                max_bytes=15 * 1024 * 1024,
            )
        except InvalidResumeDocument:
            # A declared supported resume must fail explicitly rather than being
            # mistaken for an ordinary HTML response.
            if (
                content_type in {PDF_CONTENT_TYPE, DOCX_CONTENT_TYPE}
                or response_url.casefold().endswith((".pdf", ".docx"))
                or "attachment" in disposition_lower
            ):
                raise
            return None

        return (
            body,
            canonical_type,
            normalize_resume_filename(filename, content_type=canonical_type),
        )

    @staticmethod
    def _response_pdf(response, *, probe_body: bool = True) -> bytes | None:
        """Compatibility helper retained for the existing test surface."""
        document = IndeedBrowser._response_document(response, probe_body=probe_body)
        if document is None:
            return None
        data, content_type, _filename = document
        if content_type != PDF_CONTENT_TYPE:
            return None
        return data

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
    def _response_filename_raw(response) -> str:
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
        return candidate or "indeed-resume"

    @staticmethod
    def _response_filename(response, *, content_type: str = PDF_CONTENT_TYPE) -> str:
        return normalize_resume_filename(
            IndeedBrowser._response_filename_raw(response),
            content_type=content_type,
        )

    @staticmethod
    def _requires_human(page) -> bool:
        url = str(getattr(page, "url", "") or "").casefold()
        if any(marker in url for marker in _URL_CHALLENGE_MARKERS):
            return True

        # CAPTCHA/security challenges are often rendered inside an iframe after
        # the top-level document has already loaded. Checking only body text can
        # therefore miss the challenge and leave Diagnostic mode pumping the
        # automated page indefinitely.
        try:
            for frame in list(getattr(page, "frames", []) or []):
                frame_url = str(getattr(frame, "url", "") or "").casefold()
                if any(marker in frame_url for marker in _URL_CHALLENGE_MARKERS):
                    return True
        except Exception:
            pass

        try:
            challenge_nodes = page.locator(
                'iframe[src*="captcha" i], iframe[src*="challenge" i], '
                'iframe[src*="recaptcha" i], iframe[src*="hcaptcha" i], '
                '[id*="captcha" i], [class*="captcha" i]'
            )
            if int(challenge_nodes.count()) > 0:
                return True
        except Exception:
            pass

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
            '[data-testid="menu-link-CandidatesMenu"]',
            'a[href="/candidates"]',
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

    @staticmethod
    def _is_candidates_workspace(page) -> bool:
        try:
            parsed = urlsplit(str(getattr(page, "url", "") or ""))
        except Exception:
            return False
        host = str(parsed.hostname or "").casefold()
        path = str(parsed.path or "")
        return host == "employers.indeed.com" and path.startswith("/candidates")

    @staticmethod
    def _candidate_manage_tab(page):
        # Stable attribute captured from the live Indeed Candidates DOM.
        try:
            locator = page.locator('[data-testid="manage-candidates-tab"]')
            if locator.count() > 0:
                return locator.first
        except Exception:
            pass

        name = re.compile(
            r"^(?:gestionar candidatos|manage candidates)$",
            re.IGNORECASE,
        )
        for role in ("tab", "link", "button"):
            try:
                locator = page.get_by_role(role, name=name)
                if locator.count() > 0:
                    return locator.first
            except Exception:
                continue
        try:
            locator = page.get_by_text(name)
            if locator.count() > 0:
                return locator.first
        except Exception:
            pass
        return None

    @staticmethod
    def _candidate_all_stage_tab(page):
        # Search across every application status. Indeed remembers the last
        # selected stage, which otherwise can hide an existing candidate.
        try:
            locator = page.locator('[data-testid="stage-tab-All"]')
            if locator.count() > 0:
                return locator.first
        except Exception:
            pass

        name = re.compile(
            r"^(?:todas las solicitudes|all applications|all applicants)(?:\s*[•·-]\s*\d+)?$",
            re.IGNORECASE,
        )
        for role in ("tab", "button", "link"):
            try:
                locator = page.get_by_role(role, name=name)
                if locator.count() > 0:
                    return locator.first
            except Exception:
                continue
        return None

    @staticmethod
    def _locator_selected(locator) -> bool:
        try:
            return str(locator.get_attribute("aria-selected") or "").casefold() == "true"
        except Exception:
            return False

    @staticmethod
    def _candidate_list_ready(page) -> bool:
        for selector in (
            '[data-testid="candidate-list-table-container"]',
            'a[data-testid="NameCell"]',
            'input[placeholder="Buscar candidatos" i]',
            'input[placeholder="Search candidates" i]',
        ):
            try:
                if page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        return False

    def _open_candidates_workspace(self, page) -> bool:
        # Prefer the canonical Candidates URL.
        try:
            page.goto(
                _INDEED_CANDIDATES_HOME,
                wait_until="domcontentloaded",
                timeout=int(self._config.request_timeout_seconds * 1000),
            )
        except Exception:
            pass

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
            if self._requires_human(page):
                return False

            if self._is_candidates_workspace(page):
                manage_tab = self._candidate_manage_tab(page)
                if manage_tab is not None and not self._locator_selected(manage_tab):
                    try:
                        manage_tab.click()
                        page.wait_for_timeout(400)
                    except Exception:
                        pass

                all_stage = self._candidate_all_stage_tab(page)
                if all_stage is not None and not self._locator_selected(all_stage):
                    try:
                        all_stage.click()
                        page.wait_for_timeout(400)
                    except Exception:
                        pass

                # /candidates is a client-rendered SPA. Do not start the lookup
                # until the actual list/search UI has mounted.
                if self._candidate_list_ready(page):
                    return True

            try:
                page.wait_for_timeout(interval_ms)
            except Exception:
                time.sleep(interval_ms / 1000.0)

        # Some Indeed experiments route /candidates back through Smart
        # Recruiting. Keep the semantic left-rail navigation as a fallback.
        control = self._candidate_navigation_control(page)
        if control is not None:
            try:
                control.click()
            except Exception:
                return False

            for _ in range(12):
                if self._requires_human(page):
                    return False
                if self._is_candidates_workspace(page) and self._candidate_list_ready(page):
                    return True
                try:
                    page.wait_for_timeout(interval_ms)
                except Exception:
                    time.sleep(interval_ms / 1000.0)

        return False

    @staticmethod
    def _candidate_search_box(page):
        # These placeholders come from the live Indeed Candidates DOM. Keep
        # exact selectors first, then broader fallbacks for locale/experiment
        # variations.
        for selector in (
            'input[placeholder="Buscar candidatos" i]',
            'input[placeholder="Search candidates" i]',
            'input[placeholder*="candidat" i]',
            'input[placeholder*="buscar" i]',
            'input[placeholder*="search" i]',
            'input[type="search"]',
            'input[name*="search" i]',
            '[role="searchbox"]',
        ):
            try:
                located = page.locator(selector)
                if located.count() > 0:
                    return located.first
            except Exception:
                continue

        try:
            by_role = page.get_by_role(
                "textbox",
                name=re.compile(r"(?:buscar|search).*candidat", re.IGNORECASE),
            )
            if by_role.count() > 0:
                return by_role.first
        except Exception:
            pass
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

    @staticmethod
    def _normalize_lookup_text(value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.casefold()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return " ".join(text.split())

    def _candidate_name_links(self, page):
        # Indeed has rendered candidate names in several shapes across releases:
        # an anchor carrying NameCell, a wrapper carrying NameCell with a child
        # anchor, or a row whose name cell is not itself a link. Prefer the most
        # specific live selectors first.
        for selector in (
            'a[data-testid="NameCell"][href*="/candidates/view"]',
            '[data-testid="NameCell"]',
            'a[href*="/candidates/view"]',
        ):
            try:
                locator = page.locator(selector)
                if locator.count() > 0:
                    return locator
            except Exception:
                continue
        return None

    @staticmethod
    def _candidate_click_target(node):
        # If NameCell is only a wrapper, descend to the actual clickable target.
        for selector in (
            'a[href*="/candidates/view"]',
            'a[href*="/candidates/"]',
            'a',
            'button',
        ):
            try:
                child = node.locator(selector)
                if child.count() > 0:
                    return child.first
            except Exception:
                continue
        return node

    @staticmethod
    def _candidate_row_for_node(node):
        for selector in (
            "xpath=ancestor::*[@data-testid='table-row'][1]",
            "xpath=ancestor::tbody[@data-testid='table-row'][1]",
            "xpath=ancestor::tr[1]",
        ):
            try:
                row = node.locator(selector)
                if row.count() > 0:
                    return row.first
            except Exception:
                continue
        return None

    @staticmethod
    def _candidate_rows(page):
        for selector in (
            '[data-testid="table-row"]',
            'tbody[data-testid="table-row"]',
            'tr',
        ):
            try:
                rows = page.locator(selector)
                if rows.count() > 0:
                    return rows
            except Exception:
                continue
        return None

    def _candidate_match_from_rows(
        self,
        page,
        target_name: str,
        target_job: str,
    ):
        rows = self._candidate_rows(page)
        if rows is None:
            return None, False

        matches: list[tuple[object, bool]] = []
        try:
            count = min(int(rows.count()), 100)
        except Exception:
            count = 0

        for index in range(count):
            try:
                row = rows.nth(index)
                row_text = self._normalize_lookup_text(row.inner_text(timeout=750))
                if not row_text:
                    continue

                # In the live table the candidate name is the first meaningful
                # text in the row. Accept a boundary match as a fallback when
                # the NameCell test id is absent, but never fuzzy-match names.
                boundary_match = (
                    row_text == target_name
                    or row_text.startswith(target_name + " ")
                    or f" {target_name} " in f" {row_text} "
                )
                if not boundary_match:
                    continue

                click_target = None
                for selector in (
                    '[data-testid="NameCell"]',
                    'a[href*="/candidates/view"]',
                    'a[href*="/candidates/"]',
                    'a',
                ):
                    try:
                        located = row.locator(selector)
                        if located.count() > 0:
                            click_target = located.first
                            break
                    except Exception:
                        continue
                if click_target is None:
                    click_target = row

                job_matches = bool(target_job and target_job in row_text)
                matches.append((click_target, job_matches))
            except Exception:
                continue

        if not matches:
            return None, False
        if target_job:
            job_matches = [node for node, matched in matches if matched]
            if len(job_matches) == 1:
                return job_matches[0], False
            if len(job_matches) > 1:
                return None, True
        if len(matches) == 1:
            return matches[0][0], False
        return None, True

    def _find_exact_candidate_link(
        self,
        page,
        candidate_name: str,
        *,
        job_title: str | None = None,
    ):
        target_name = self._normalize_lookup_text(candidate_name)
        target_job = self._normalize_lookup_text(job_title)
        if not target_name:
            return None, False

        links = self._candidate_name_links(page)
        matches: list[tuple[object, bool]] = []

        if links is not None:
            try:
                count = min(int(links.count()), 100)
            except Exception:
                count = 0

            for index in range(count):
                try:
                    node = links.nth(index)
                    label = self._normalize_lookup_text(node.inner_text(timeout=500))
                    if label != target_name:
                        continue

                    row = self._candidate_row_for_node(node)
                    row_text = ""
                    if row is not None:
                        try:
                            row_text = self._normalize_lookup_text(
                                row.inner_text(timeout=750)
                            )
                        except Exception:
                            row_text = ""

                    job_matches = bool(target_job and target_job in row_text)
                    matches.append((self._candidate_click_target(node), job_matches))
                except Exception:
                    continue

        if not matches:
            # Row-level fallback handles alternate Indeed layouts where the name
            # is rendered in a non-anchor NameCell or the test id is absent.
            row_match, row_ambiguous = self._candidate_match_from_rows(
                page, target_name, target_job
            )
            if row_match is not None or row_ambiguous:
                return row_match, row_ambiguous

            # Last semantic fallback for experiments that expose the candidate
            # name to the accessibility tree but do not use the observed table
            # markup. Keep it exact and normalized; never fuzzy-click.
            try:
                exact = page.get_by_text(
                    re.compile(rf"^\s*{re.escape(candidate_name)}\s*$", re.IGNORECASE)
                )
                if exact.count() == 1:
                    return exact.first, False
                if exact.count() > 1:
                    return None, True
            except Exception:
                pass
            return None, False

        if target_job:
            job_matches = [node for node, matched in matches if matched]
            if len(job_matches) == 1:
                return job_matches[0], False
            if len(job_matches) > 1:
                return None, True

        if len(matches) == 1:
            return matches[0][0], False

        # Multiple candidates with the same normalized name are unsafe to guess.
        return None, True

    @staticmethod
    def _candidate_search_url(query: str) -> str:
        # Captured from the live Indeed Candidates UI: searching from
        # "Gestionar candidatos" serializes the search as
        # /candidates?statusName=All&tab=manage&q=<candidate>.
        # Navigating to the same first-party URL is substantially more stable
        # than depending only on a React textbox selector.
        return (
            f"{_INDEED_CANDIDATES_HOME}"
            f"?statusName=All&tab=manage&q={quote_plus(str(query or '').strip())}"
        )

    @classmethod
    def _candidate_search_queries(cls, candidate_name: str) -> list[str]:
        original = " ".join(str(candidate_name or "").split()).strip()
        if not original:
            return []

        normalized = cls._normalize_lookup_text(original)
        queries = [original]
        if normalized and normalized.casefold() != original.casefold():
            queries.append(normalized)

        tokens = normalized.split()
        if len(tokens) >= 3:
            short = f"{tokens[0]} {tokens[-1]}"
            if short not in queries:
                queries.append(short)

        # Preserve order and avoid repeated searches.
        unique: list[str] = []
        seen: set[str] = set()
        for query in queries:
            key = query.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(query)
        return unique

    def _open_candidate_from_list(
        self,
        page,
        candidate_name: str,
        *,
        job_title: str | None = None,
    ):
        name = " ".join(str(candidate_name or "").split()).strip()
        if not name:
            return None, "INDEED_CANDIDATE_NAME_MISSING"

        if not self._open_candidates_workspace(page):
            if self._requires_human(page):
                return None, "INDEED_AUTH_REQUIRED"
            return None, "INDEED_CANDIDATES_WORKSPACE_UNAVAILABLE"

        if self._requires_human(page):
            return None, "INDEED_AUTH_REQUIRED"

        # First inspect the currently rendered rows. This is cheap and avoids
        # touching the search field when the candidate is already visible.
        candidate, ambiguous = self._find_exact_candidate_link(
            page,
            name,
            job_title=job_title,
        )
        if ambiguous:
            return None, "INDEED_CANDIDATE_AMBIGUOUS"
        if candidate is not None:
            try:
                candidate.click()
                control = self._wait_for_download_control(page)
                return (
                    (control, None)
                    if control is not None
                    else (None, "INDEED_CANDIDATE_DETAIL_NO_DOWNLOAD")
                )
            except Exception:
                return None, "INDEED_CANDIDATE_OPEN_FAILED"

        lookup_budget = max(8.0, float(self._config.request_timeout_seconds))
        deadline = time.monotonic() + lookup_budget
        queries = self._candidate_search_queries(name)
        search_box = None
        search_route_worked = False

        for query_index, query in enumerate(queries):
            if time.monotonic() >= deadline:
                break

            # Primary path: use the first-party URL generated by Indeed itself
            # when a recruiter searches in Manage candidates. The diagnostic
            # trace showed this exact shape with statusName=All, tab=manage and
            # q=<candidate name>.
            try:
                page.goto(
                    self._candidate_search_url(query),
                    wait_until="domcontentloaded",
                    timeout=int(self._config.request_timeout_seconds * 1000),
                )
                search_route_worked = self._is_candidates_workspace(page)
            except Exception:
                search_route_worked = False

            query_deadline = min(deadline, time.monotonic() + 5.0)
            while time.monotonic() < query_deadline:
                if self._requires_human(page):
                    return None, "INDEED_AUTH_REQUIRED"

                candidate, ambiguous = self._find_exact_candidate_link(
                    page,
                    name,
                    job_title=job_title,
                )
                if ambiguous:
                    return None, "INDEED_CANDIDATE_AMBIGUOUS"
                if candidate is not None:
                    try:
                        candidate.click()
                    except Exception:
                        return None, "INDEED_CANDIDATE_OPEN_FAILED"
                    control = self._wait_for_download_control(page)
                    return (
                        (control, None)
                        if control is not None
                        else (None, "INDEED_CANDIDATE_DETAIL_NO_DOWNLOAD")
                    )

                if search_box is None:
                    search_box = self._candidate_search_box(page)

                try:
                    page.wait_for_timeout(400)
                except Exception:
                    time.sleep(0.4)

                if self._candidate_list_ready(page):
                    break

            # Secondary path: exercise the visible search control when present.
            # This keeps compatibility with Indeed experiments that ignore q.
            if search_box is None:
                search_box = self._candidate_search_box(page)

            if search_box is not None:
                try:
                    search_box.fill("")
                    search_box.fill(query)
                except Exception:
                    search_box = None
                else:
                    input_deadline = min(deadline, time.monotonic() + 4.5)
                    pressed_enter = False
                    polls = 0
                    while time.monotonic() < input_deadline:
                        if self._requires_human(page):
                            return None, "INDEED_AUTH_REQUIRED"

                        candidate, ambiguous = self._find_exact_candidate_link(
                            page,
                            name,
                            job_title=job_title,
                        )
                        if ambiguous:
                            return None, "INDEED_CANDIDATE_AMBIGUOUS"
                        if candidate is not None:
                            try:
                                candidate.click()
                            except Exception:
                                return None, "INDEED_CANDIDATE_OPEN_FAILED"
                            control = self._wait_for_download_control(page)
                            return (
                                (control, None)
                                if control is not None
                                else (None, "INDEED_CANDIDATE_DETAIL_NO_DOWNLOAD")
                            )

                        polls += 1
                        if not pressed_enter and polls >= 3:
                            try:
                                search_box.press("Enter")
                            except Exception:
                                pass
                            pressed_enter = True
                        if polls >= 8:
                            break
                        try:
                            page.wait_for_timeout(500)
                        except Exception:
                            time.sleep(0.5)

            search_box = None

        if not search_route_worked and self._candidate_search_box(page) is None:
            return None, "INDEED_CANDIDATE_SEARCH_UNAVAILABLE"
        return None, "INDEED_CANDIDATE_NOT_FOUND"

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
            except Exception:
                continue

            if self._requires_human(page):
                self._diagnostic_active = False
                self.close()
                raise RuntimeError("INDEED_MANUAL_LOGIN_REQUIRED")

            try:
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

    def _write_ui_diagnostic(
        self,
        page,
        *,
        reason: str | None = None,
    ) -> str | None:
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

        inputs: list[dict[str, str]] = []
        try:
            items = page.locator("input")
            count = min(int(items.count()), 40)
        except Exception:
            count = 0
            items = None
        for index in range(count):
            try:
                node = items.nth(index)
                if not node.is_visible():
                    continue
                inputs.append(
                    {
                        "type": str(node.get_attribute("type") or "")[:80],
                        "name": str(node.get_attribute("name") or "")[:120],
                        "placeholder": str(node.get_attribute("placeholder") or "")[:200],
                        "aria_label": str(node.get_attribute("aria-label") or "")[:200],
                    }
                )
            except Exception:
                continue

        payload = {
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "url": _safe_diagnostic_url(getattr(page, "url", "")),
            "title": title,
            "reason": str(reason or "")[:120],
            "controls": controls,
            "inputs": inputs,
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
        job_title: str | None = None,
    ) -> BrowserResult:
        try:
            self.start()
        except Exception as exc:
            raise BrowserFetchStageError("RESUME_BROWSER_START_FAILED") from exc

        resume_url = str(url or "").strip()
        if not resume_url.lower().startswith("https://"):
            return BrowserResult(
                BrowserOutcome.NEEDS_HUMAN,
                human_code="INDEED_UI_REQUIRES_REVIEW",
            )

        # Fast path: the ephemeral Indeed link can occasionally resolve directly
        # to a supported document without rendering the employer SPA.
        try:
            response = self._context.request.get(
                resume_url,
                timeout=int(self._config.request_timeout_seconds * 1000),
            )
            direct = self._response_document(response)
            if direct is not None:
                data, content_type, filename = direct
                validate_resume_document(
                    data,
                    filename=filename,
                    content_type=content_type,
                    max_bytes=self._config.max_pdf_bytes,
                )
                return BrowserResult(
                    BrowserOutcome.DOWNLOADED,
                    filename=filename,
                    data=data,
                    content_type=content_type,
                )
        except InvalidResumeDocument:
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
            navigated_document = self._response_document(
                navigation,
                probe_body=False,
            )
        except InvalidResumeDocument:
            raise
        except Exception as exc:
            raise BrowserFetchStageError(
                "RESUME_BROWSER_NAVIGATION_RESPONSE_FAILED"
            ) from exc

        if navigated_document is not None:
            data, content_type, filename = navigated_document
            validate_resume_document(
                data,
                filename=filename,
                content_type=content_type,
                max_bytes=self._config.max_pdf_bytes,
            )
            return BrowserResult(
                BrowserOutcome.DOWNLOADED,
                filename=filename,
                data=data,
                content_type=content_type,
            )

        generic_landing = self._is_generic_recruiting_landing(page)
        control = None if generic_landing else self._wait_for_download_control(page)

        if self._requires_human(page):
            return BrowserResult(
                BrowserOutcome.NEEDS_HUMAN,
                human_code="INDEED_AUTH_REQUIRED",
            )

        fallback_attempted = False
        lookup_error: str | None = None
        if (generic_landing or control is None) and str(candidate_name or "").strip():
            fallback_attempted = True
            control, lookup_error = self._open_candidate_from_list(
                page,
                str(candidate_name),
                job_title=job_title,
            )

        if self._requires_human(page):
            return BrowserResult(
                BrowserOutcome.NEEDS_HUMAN,
                human_code="INDEED_AUTH_REQUIRED",
            )

        if control is None:
            reason = lookup_error or (
                "INDEED_CANDIDATE_NOT_FOUND"
                if fallback_attempted
                else "INDEED_UI_REQUIRES_REVIEW"
            )
            diagnostic_path = self._write_ui_diagnostic(page, reason=reason)
            return BrowserResult(
                BrowserOutcome.NEEDS_HUMAN,
                human_code=reason,
                diagnostic_path=diagnostic_path,
            )

        captured_document: dict[str, object] = {}

        def capture_resume_response(response) -> None:
            if not self._is_resume_download_response(response):
                return
            try:
                document = self._response_document(response)
                if document is None:
                    return
                data, content_type, filename = document
                validate_resume_document(
                    data,
                    filename=filename,
                    content_type=content_type,
                    max_bytes=self._config.max_pdf_bytes,
                )
                captured_document["data"] = data
                captured_document["filename"] = filename
                captured_document["content_type"] = content_type
            except InvalidResumeDocument as exc:
                captured_document["invalid_code"] = exc.code
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

            invalid_code = captured_document.get("invalid_code")
            if invalid_code:
                raise InvalidResumeDocument(str(invalid_code))

            if isinstance(captured_document.get("data"), (bytes, bytearray)):
                return BrowserResult(
                    BrowserOutcome.DOWNLOADED,
                    filename=str(
                        captured_document.get("filename") or "indeed-resume.pdf"
                    ),
                    data=bytes(captured_document["data"]),
                    content_type=str(
                        captured_document.get("content_type") or PDF_CONTENT_TYPE
                    ),
                )

            download = download_info.value
            suggested = str(
                getattr(download, "suggested_filename", None) or "indeed-resume"
            )
            path = download.path()
            data = Path(path).read_bytes()
            content_type = validate_resume_document(
                data,
                filename=suggested,
                content_type=None,
                max_bytes=self._config.max_pdf_bytes,
            )
            return BrowserResult(
                BrowserOutcome.DOWNLOADED,
                filename=normalize_resume_filename(
                    suggested,
                    content_type=content_type,
                ),
                data=data,
                content_type=content_type,
            )
        except InvalidResumeDocument:
            raise
        except Exception:
            # Indeed can finish the authenticated response even if the Download
            # object becomes unavailable because the SPA/tab closes. Prefer the
            # already captured response in that case.
            invalid_code = captured_document.get("invalid_code")
            if invalid_code:
                raise InvalidResumeDocument(str(invalid_code))
            if isinstance(captured_document.get("data"), (bytes, bytearray)):
                return BrowserResult(
                    BrowserOutcome.DOWNLOADED,
                    filename=str(
                        captured_document.get("filename") or "indeed-resume.pdf"
                    ),
                    data=bytes(captured_document["data"]),
                    content_type=str(
                        captured_document.get("content_type") or PDF_CONTENT_TYPE
                    ),
                )

            diagnostic_path = self._write_ui_diagnostic(
                page,
                reason="INDEED_DOWNLOAD_ACTION_REQUIRES_REVIEW",
            )
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

