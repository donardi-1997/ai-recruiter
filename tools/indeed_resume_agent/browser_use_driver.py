from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import json
import os
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from email.header import decode_header, make_header
from urllib.parse import quote_plus, unquote, urljoin, urlsplit

from .browser import (
    BrowserFetchStageError,
    BrowserOutcome,
    BrowserResult,
    DOCX_CONTENT_TYPE,
    PDF_CONTENT_TYPE,
    _resolve_browser_executable,
    _safe_diagnostic_text,
    _safe_diagnostic_url,
    normalize_resume_filename,
    validate_resume_document,
)
from .config import AgentConfig


_INDEED_CANDIDATES_HOME = "https://employers.indeed.com/candidates"
_INDEED_RESUME_DOWNLOAD_PATH = "/api/catws/resume/v2/download"
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
    "verify you are human",
    "verifica que eres humano",
)
_URL_CHALLENGE_MARKERS = ("/login", "/signin", "challenge", "captcha", "verify")
_FILENAME_STAR = re.compile(r"filename\*=UTF-8''([^;]+)", re.IGNORECASE)
_FILENAME_BASIC = re.compile(r'filename="?([^";]+)"?', re.IGNORECASE)


def _runtime_value(result):
    if isinstance(result, dict):
        payload = result.get("result")
        if isinstance(payload, dict):
            return payload.get("value")
    return None


def _normalize_lookup_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _candidate_recency_key(row: dict) -> tuple[int, float, int]:
    """Sort candidate applications newest-first using provider date, then relative text."""
    raw = str(row.get("appliedAt") or "").strip()
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return (3, parsed.timestamp(), -int(row.get("index") or 0))
        except (TypeError, ValueError, OverflowError):
            pass

    text = _normalize_lookup_text(row.get("rowText"))
    if "hoy" in text or "today" in text:
        return (2, 0.0, -int(row.get("index") or 0))
    if "ayer" in text or "yesterday" in text:
        return (2, -86400.0, -int(row.get("index") or 0))

    units = (
        (r"(?:hace|ago)\s+(\d+)\s*(?:minuto|minutos|minute|minutes|min)", 60),
        (r"(?:hace|ago)\s+(\d+)\s*(?:hora|horas|hour|hours|hr)", 3600),
        (r"(?:hace|ago)\s+(\d+)\s*(?:dia|dias|day|days)", 86400),
        (r"(?:hace|ago)\s+(\d+)\s*(?:semana|semanas|week|weeks)", 604800),
        (r"(?:hace|ago)\s+(\d+)\s*(?:mes|meses|month|months)", 2629800),
        (r"(?:hace|ago)\s+(\d+)\s*(?:ano|anos|year|years)", 31557600),
    )
    for pattern, seconds in units:
        match = re.search(pattern, text)
        if match:
            age = int(match.group(1)) * seconds
            return (2, -float(age), -int(row.get("index") or 0))

    # Indeed normally keeps equal-name rows in provider order even when the
    # visible primary sort is by name. Prefer the first row as deterministic
    # fallback instead of blocking the entire queue.
    return (1, 0.0, -int(row.get("index") or 0))


def _candidate_search_queries(candidate_name: str) -> list[str]:
    original = " ".join(str(candidate_name or "").split()).strip()
    if not original:
        return []
    normalized = _normalize_lookup_text(original)
    queries = [original]
    if normalized and normalized.casefold() != original.casefold():
        queries.append(normalized)
    tokens = normalized.split()
    if len(tokens) >= 3:
        queries.append(f"{tokens[0]} {tokens[-1]}")
    unique: list[str] = []
    seen: set[str] = set()
    for query in queries:
        key = query.casefold()
        if key and key not in seen:
            seen.add(key)
            unique.append(query)
    return unique


def _candidate_search_url(query: str) -> str:
    return (
        f"{_INDEED_CANDIDATES_HOME}"
        f"?statusName=All&tab=manage&q={quote_plus(str(query or '').strip())}"
    )


def _safe_indeed_url(raw_url: str | None) -> str:
    value = str(raw_url or "").strip()
    if not value:
        return _INDEED_CANDIDATES_HOME
    try:
        parsed = urlsplit(value)
    except Exception:
        return _INDEED_CANDIDATES_HOME
    host = str(parsed.hostname or "").casefold()
    allowed = (
        host == "indeed.com"
        or host.endswith(".indeed.com")
        or host == "indeedemail.com"
        or host.endswith(".indeedemail.com")
        or host == "accounts.google.com"
    )
    if parsed.scheme.casefold() != "https" or not allowed:
        return _INDEED_CANDIDATES_HOME
    return value


def _is_resume_download_url(raw_url: str | None) -> bool:
    try:
        parsed = urlsplit(str(raw_url or ""))
    except Exception:
        return False
    return (
        str(parsed.hostname or "").casefold() == "employers.indeed.com"
        and str(parsed.path or "") == _INDEED_RESUME_DOWNLOAD_PATH
    )


def _decode_filename(content_disposition: str | None) -> str | None:
    value = str(content_disposition or "")
    star = _FILENAME_STAR.search(value)
    if star:
        return unquote(star.group(1).strip().strip('"'))
    basic = _FILENAME_BASIC.search(value)
    if not basic:
        return None
    raw = basic.group(1).strip().strip('"')
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


def _sanitize_browser_use_args() -> None:
    """Apply the Chrome compatibility patch already proven in job-agent."""
    try:
        import browser_use.browser.profile as browser_use_profile
    except Exception:
        return
    args = getattr(browser_use_profile, "CHROME_DEFAULT_ARGS", None)
    if not isinstance(args, list):
        return
    while "--extensions-on-chrome-urls" in args:
        args.remove("--extensions-on-chrome-urls")


def _configure_browser_use_environment() -> None:
    # This desktop agent does not use Browser Use cloud services or product
    # telemetry. Keep recruiter browsing/session metadata local to the machine.
    os.environ["BROWSER_USE_SETUP_LOGGING"] = "false"
    os.environ["ANONYMIZED_TELEMETRY"] = "false"
    os.environ["BROWSER_USE_CLOUD_SYNC"] = "false"


def _load_browser_session_class():
    _configure_browser_use_environment()
    _sanitize_browser_use_args()
    from browser_use.browser.session import BrowserSession

    return BrowserSession


class IndeedBrowserUse:
    """Deterministic Indeed driver built on Browser Use + direct CDP.

    Browser Use owns one persistent visible Chrome instance. Navigation,
    candidate matching and clicks are deterministic; no Agent/LLM is involved.
    Resume bytes are captured from Chrome's Network domain instead of relying on
    the Windows Downloads UI.
    """

    def __init__(
        self,
        config: AgentConfig,
        *,
        browser_session_class=None,
        browser_executable_resolver=None,
    ) -> None:
        self._config = config
        self._browser_name = str(config.browser_name or "chrome").strip().casefold()
        if self._browser_name == "chrome":
            self._browser_label = "Google Chrome"
        elif self._browser_name == "edge":
            self._browser_label = "Microsoft Edge"
        else:
            raise ValueError(f"Navegador no soportado: {self._browser_name}")

        self._browser_session_class = browser_session_class
        self._browser_executable_resolver = (
            browser_executable_resolver
            or (lambda: _resolve_browser_executable(self._browser_name))
        )

        self._browser = None
        self._network_registered = False
        self._resume_response_meta: dict[str, dict] = {}
        self._download_future: asyncio.Future | None = None
        self._diagnostic_active = False
        self._diagnostic_events: list[dict] = []
        self._diagnostic_started_at: str | None = None
        self._last_diagnostic_path: str | None = None

        self._closed = False
        self._loop = asyncio.new_event_loop()
        self._loop_ready = threading.Event()
        self._loop_thread = threading.Thread(
            target=self._run_loop,
            name="asiati-browser-use",
            daemon=True,
        )
        self._loop_thread.start()
        self._loop_ready.wait(timeout=5.0)

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
        # Manual login and automation use the same Browser Use-owned Chrome.
        return False

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        self._loop.run_forever()
        pending = asyncio.all_tasks(self._loop)
        for task in pending:
            task.cancel()
        if pending:
            self._loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
        self._loop.close()

    def _call(self, coro, *, timeout: float | None = None):
        if self._closed:
            raise RuntimeError("BROWSER_USE_DRIVER_CLOSED")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        resolved_timeout = timeout or max(
            60.0,
            float(self._config.request_timeout_seconds) * 4.0,
        )
        try:
            return future.result(timeout=resolved_timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TimeoutError("BROWSER_USE_OPERATION_TIMEOUT") from exc

    async def _discard_browser_session(self) -> None:
        browser = self._browser
        self._browser = None
        self._network_registered = False
        self._download_future = None
        self._resume_response_meta.clear()
        if browser is not None:
            try:
                await browser.stop()
            except Exception:
                pass

    async def _ensure_started_once(self):
        if self._browser is None:
            session_class = self._browser_session_class or _load_browser_session_class()
            self._config.browser_profile_dir.mkdir(parents=True, exist_ok=True)
            executable = self._browser_executable_resolver()
            self._browser = session_class(
                executable_path=executable,
                user_data_dir=str(self._config.browser_profile_dir.resolve()),
                headless=False,
                allowed_domains=[
                    "indeed.com",
                    "*.indeed.com",
                    "indeedemail.com",
                    "*.indeedemail.com",
                    "accounts.google.com",
                ],
                accept_downloads=True,
                auto_download_pdfs=False,
                enable_default_extensions=False,
                captcha_solver=False,
                chromium_sandbox=True,
                highlight_elements=False,
                dom_highlight_elements=False,
            )
            await self._browser.start()
            self._network_registered = False

        cdp = await self._browser.get_or_create_cdp_session(
            self._browser.agent_focus_target_id,
            focus=True,
        )
        await cdp.cdp_client.send.Page.enable(session_id=cdp.session_id)
        await cdp.cdp_client.send.Runtime.enable(session_id=cdp.session_id)
        await cdp.cdp_client.send.Network.enable(session_id=cdp.session_id)

        if not self._network_registered:
            register = self._browser.cdp_client.register
            register.Network.responseReceived(self._on_response_received)
            register.Network.loadingFinished(self._on_loading_finished)
            register.Network.loadingFailed(self._on_loading_failed)
            self._network_registered = True
        return cdp

    async def _ensure_started(self):
        had_existing_session = self._browser is not None
        try:
            return await self._ensure_started_once()
        except Exception:
            if not had_existing_session:
                raise
            # The user may have closed the Browser Use-owned Chrome window.
            # Recreate the stale CDP session once using the same persistent
            # profile instead of leaving the agent poisoned until restart.
            await self._discard_browser_session()
            return await self._ensure_started_once()

    def start(self) -> None:
        self._call(self._ensure_started())

    def reset_session(self) -> None:
        """Discard only the current Browser Use session and keep the driver reusable."""
        if self._closed:
            return
        try:
            self._call(self._discard_browser_session(), timeout=30.0)
        except Exception:
            pass

    async def _async_close(self) -> None:
        self._diagnostic_active = False
        await self._discard_browser_session()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._call(self._async_close(), timeout=30.0)
        except Exception:
            pass
        self._closed = True
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            return
        self._loop_thread.join(timeout=5.0)

    async def _evaluate(self, cdp, expression: str):
        result = await cdp.cdp_client.send.Runtime.evaluate(
            params={
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
            session_id=cdp.session_id,
        )
        return _runtime_value(result)

    async def _wait_ready(self, cdp, *, extra_delay: float = 0.35) -> None:
        deadline = time.monotonic() + max(
            8.0,
            float(self._config.request_timeout_seconds),
        )
        while time.monotonic() < deadline:
            state = await self._evaluate(
                cdp,
                "(() => ({ready: document.readyState, url: location.href}))()",
            )
            if isinstance(state, dict) and state.get("ready") in {
                "interactive",
                "complete",
            }:
                await asyncio.sleep(extra_delay)
                return
            await asyncio.sleep(0.25)
        raise BrowserFetchStageError("INDEED_NAVIGATION_TIMEOUT")

    async def _navigate(self, cdp, url: str) -> None:
        await cdp.cdp_client.send.Page.navigate(
            params={"url": _safe_indeed_url(url)},
            session_id=cdp.session_id,
        )
        await self._wait_ready(cdp)

    async def _page_state(self, cdp) -> dict:
        script = r"""
(() => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const iframes = Array.from(document.querySelectorAll('iframe'))
    .map((el) => String(el.src || ''))
    .filter(Boolean)
    .slice(0, 50);
  return {
    url: location.href,
    title: document.title || '',
    body: clean(document.body?.innerText || '').slice(0, 12000),
    iframes,
  };
})()
"""
        value = await self._evaluate(cdp, script)
        return value if isinstance(value, dict) else {}

    async def _requires_human(self, cdp) -> bool:
        state = await self._page_state(cdp)
        url = str(state.get("url") or "").casefold()
        if any(marker in url for marker in _URL_CHALLENGE_MARKERS):
            return True
        for frame_url in state.get("iframes") or []:
            candidate = str(frame_url or "").casefold()
            if any(marker in candidate for marker in _URL_CHALLENGE_MARKERS):
                return True
        body = str(state.get("body") or "").casefold()
        return any(marker in body for marker in _CHALLENGE_MARKERS)

    async def _open_indeed(self, url: str | None = None) -> None:
        cdp = await self._ensure_started()
        await self._navigate(cdp, _safe_indeed_url(url))

    def open_indeed(self, url: str | None = None) -> None:
        self._call(self._open_indeed(url))

    def _record_diagnostic_event(self, payload: dict) -> None:
        if not self._diagnostic_active:
            return
        event = dict(payload)
        event["captured_at_utc"] = datetime.now(timezone.utc).isoformat()
        self._diagnostic_events.append(event)
        if len(self._diagnostic_events) > 600:
            del self._diagnostic_events[:-600]

    def _on_response_received(self, params, session_id) -> None:
        try:
            response = params.get("response", {}) if hasattr(params, "get") else {}
            url = str(response.get("url") or "")
            status = int(response.get("status") or 0)
            headers_raw = response.get("headers") or {}
            headers = (
                {
                    str(key).casefold(): str(value)
                    for key, value in dict(headers_raw).items()
                }
                if isinstance(headers_raw, dict)
                else {}
            )
            content_type = str(
                headers.get("content-type")
                or response.get("mimeType")
                or ""
            ).split(";", 1)[0].strip().casefold()
            disposition = str(headers.get("content-disposition") or "")

            if self._diagnostic_active and "indeed" in url.casefold():
                self._record_diagnostic_event(
                    {
                        "kind": "response",
                        "status": status,
                        "url": _safe_diagnostic_url(url),
                        "content_type": content_type[:200],
                        "filename_extension": (
                            os.path.splitext(_decode_filename(disposition) or "")[1]
                            .casefold()[:16]
                        ),
                    }
                )

            if status != 200 or not _is_resume_download_url(url):
                return
            request_id = (
                params.get("requestId")
                if hasattr(params, "get")
                else None
            )
            if not request_id:
                return
            self._resume_response_meta[str(request_id)] = {
                "headers": headers,
                "content_type": content_type,
                "session_id": session_id,
                "url": url,
            }
        except Exception:
            return

    def _on_loading_finished(self, params, session_id) -> None:
        try:
            request_id = str(
                params.get("requestId")
                if hasattr(params, "get")
                else ""
            )
            if request_id not in self._resume_response_meta:
                return
            asyncio.create_task(
                self._capture_resume_body(
                    request_id,
                    session_id
                    or self._resume_response_meta[request_id].get("session_id"),
                )
            )
        except Exception:
            return

    def _on_loading_failed(self, params, session_id) -> None:
        try:
            request_id = str(
                params.get("requestId")
                if hasattr(params, "get")
                else ""
            )
            if request_id in self._resume_response_meta:
                self._resume_response_meta.pop(request_id, None)
        except Exception:
            return

    async def _capture_resume_body(self, request_id: str, session_id) -> None:
        meta = self._resume_response_meta.pop(request_id, None)
        if meta is None or self._browser is None:
            return
        future = self._download_future
        if future is None or future.done():
            return
        try:
            response = await self._browser.cdp_client.send.Network.getResponseBody(
                params={"requestId": request_id},
                session_id=session_id,
            )
            body = response.get("body", b"") if isinstance(response, dict) else b""
            if isinstance(body, str):
                if bool(response.get("base64Encoded")):
                    payload = base64.b64decode(body)
                else:
                    payload = body.encode("utf-8", errors="replace")
            else:
                payload = bytes(body or b"")

            headers = dict(meta.get("headers") or {})
            declared_type = str(meta.get("content_type") or "")
            raw_filename = _decode_filename(headers.get("content-disposition"))
            canonical_type = validate_resume_document(
                payload,
                filename=raw_filename,
                content_type=declared_type,
                max_bytes=self._config.max_pdf_bytes,
            )
            filename = normalize_resume_filename(
                raw_filename,
                content_type=canonical_type,
            )
            if not future.done():
                future.set_result(
                    BrowserResult(
                        BrowserOutcome.DOWNLOADED,
                        filename=filename,
                        data=payload,
                        content_type=canonical_type,
                    )
                )
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)

    def _arm_download(self) -> asyncio.Future:
        self._resume_response_meta.clear()
        self._download_future = self._loop.create_future()
        return self._download_future

    async def _wait_for_download(
        self,
        future: asyncio.Future,
    ) -> BrowserResult | None:
        try:
            return await asyncio.wait_for(
                asyncio.shield(future),
                timeout=max(
                    8.0,
                    float(self._config.request_timeout_seconds),
                ),
            )
        except asyncio.TimeoutError:
            return None

    async def _candidate_rows(self, cdp) -> list[dict]:
        script = r"""
(() => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const selectors = [
    'a[data-testid="NameCell"][href*="/candidates/view"]',
    '[data-testid="NameCell"]',
    'a[href*="/candidates/view"]'
  ];
  const nodes = [];
  const nodeSet = new Set();
  for (const selector of selectors) {
    for (const node of document.querySelectorAll(selector)) {
      if (nodeSet.has(node)) continue;
      nodeSet.add(node);
      nodes.push(node);
    }
  }
  const seen = new Set();
  const out = [];
  for (const [index, node] of nodes.slice(0, 120).entries()) {
    const link = node.matches?.('a[href]')
      ? node
      : node.querySelector?.('a[href*="/candidates/"]')
        || node.closest?.('a[href*="/candidates/"]');
    const row = node.closest?.(
      '[data-testid="table-row"], tbody[data-testid="table-row"], tr'
    ) || node.parentElement;
    const name = clean(node.innerText || link?.innerText || '');
    const rowText = clean(row?.innerText || node.innerText || '');
    const href = String(link?.href || '');
    const timeNode = row?.querySelector?.('time[datetime]');
    const appliedAt = String(
      timeNode?.getAttribute?.('datetime')
      || row?.getAttribute?.('data-applied-at')
      || row?.getAttribute?.('data-application-date')
      || ''
    );
    const key = name + '|' + href + '|' + rowText + '|' + appliedAt;
    if (!name || seen.has(key)) continue;
    seen.add(key);
    out.push({name, rowText, href, index, appliedAt});
  }
  return out;
})()
"""
        value = await self._evaluate(cdp, script)
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    async def _click_candidate_index(self, cdp, index: int) -> bool:
        script = f"""
(() => {{
  const selectors = [
    'a[data-testid="NameCell"][href*="/candidates/view"]',
    '[data-testid="NameCell"]',
    'a[href*="/candidates/view"]'
  ];
  const nodes = [];
  const nodeSet = new Set();
  for (const selector of selectors) {{
    for (const node of document.querySelectorAll(selector)) {{
      if (nodeSet.has(node)) continue;
      nodeSet.add(node);
      nodes.push(node);
    }}
  }}
  const node = nodes[{int(index)}];
  if (!node) return false;
  const link = node.matches?.('a[href]')
    ? node
    : node.querySelector?.('a[href*="/candidates/"]')
      || node.closest?.('a[href*="/candidates/"]');
  const target = link || node;
  target.click();
  return true;
}})()
"""
        return (await self._evaluate(cdp, script)) is True

    async def _fill_candidate_search(self, cdp, query: str) -> bool:
        payload = json.dumps(str(query or ""))
        script = f"""
(() => {{
  const selectors = [
    'input[placeholder="Buscar candidatos" i]',
    'input[placeholder="Search candidates" i]',
    'input[placeholder*="candidat" i]',
    'input[type="search"]',
    '[role="searchbox"]'
  ];
  let input = null;
  for (const selector of selectors) {{
    input = document.querySelector(selector);
    if (input) break;
  }}
  if (!input) return false;
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    'value'
  )?.set;
  if (setter) setter.call(input, {payload}); else input.value = {payload};
  input.dispatchEvent(new Event('input', {{bubbles: true}}));
  input.dispatchEvent(new Event('change', {{bubbles: true}}));
  input.dispatchEvent(new KeyboardEvent(
    'keydown',
    {{key: 'Enter', code: 'Enter', bubbles: true}}
  ));
  input.dispatchEvent(new KeyboardEvent(
    'keyup',
    {{key: 'Enter', code: 'Enter', bubbles: true}}
  ));
  return true;
}})()
"""
        return (await self._evaluate(cdp, script)) is True

    @staticmethod
    def _select_candidate(
        rows: list[dict],
        candidate_name: str,
        job_title: str | None,
    ) -> tuple[dict | None, str | None]:
        target_name = _normalize_lookup_text(candidate_name)
        target_job = _normalize_lookup_text(job_title)
        exact = [
            row
            for row in rows
            if _normalize_lookup_text(row.get("name")) == target_name
        ]
        if not exact:
            return None, None
        if target_job:
            job_matches = [
                row
                for row in exact
                if target_job in _normalize_lookup_text(row.get("rowText"))
            ]
            if job_matches:
                return max(job_matches, key=_candidate_recency_key), None
            # Never fall back to another vacancy for the same person.
            return None, None
        if exact:
            return max(exact, key=_candidate_recency_key), None
        return None, None

    async def _open_candidate(
        self,
        cdp,
        candidate_name: str,
        job_title: str | None,
    ) -> str | None:
        name = " ".join(str(candidate_name or "").split()).strip()
        if not name:
            return "INDEED_CANDIDATE_NAME_MISSING"

        for query in _candidate_search_queries(name):
            await self._navigate(cdp, _candidate_search_url(query))
            if await self._requires_human(cdp):
                return "INDEED_AUTH_REQUIRED"

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                rows = await self._candidate_rows(cdp)
                target, error = self._select_candidate(rows, name, job_title)
                if error:
                    return error
                if target:
                    href = str(target.get("href") or "")
                    if href:
                        await self._navigate(
                            cdp,
                            urljoin("https://employers.indeed.com/", href),
                        )
                    else:
                        try:
                            index = int(target.get("index"))
                        except (TypeError, ValueError):
                            return "INDEED_CANDIDATE_OPEN_FAILED"
                        if not await self._click_candidate_index(cdp, index):
                            return "INDEED_CANDIDATE_OPEN_FAILED"
                        await asyncio.sleep(0.5)
                    return None
                await asyncio.sleep(0.35)

            if await self._fill_candidate_search(cdp, query):
                await asyncio.sleep(1.0)
                rows = await self._candidate_rows(cdp)
                target, error = self._select_candidate(rows, name, job_title)
                if error:
                    return error
                if target:
                    href = str(target.get("href") or "")
                    if href:
                        await self._navigate(
                            cdp,
                            urljoin("https://employers.indeed.com/", href),
                        )
                    else:
                        try:
                            index = int(target.get("index"))
                        except (TypeError, ValueError):
                            return "INDEED_CANDIDATE_OPEN_FAILED"
                        if not await self._click_candidate_index(cdp, index):
                            return "INDEED_CANDIDATE_OPEN_FAILED"
                        await asyncio.sleep(0.5)
                    return None

        return "INDEED_CANDIDATE_NOT_FOUND"

    async def _click_download_control(self, cdp) -> bool:
        script = r"""
(() => {
  const clean = (v) => String(v || '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
  const exactLabels = new Set([
    'descargar cv', 'descargar resume', 'descargar currículum',
    'descargar curriculum', 'descargar hoja de vida',
    'download cv', 'download resume', 'view cv', 'view resume',
    'ver cv', 'ver currículum', 'ver curriculum', 'ver hoja de vida'
  ]);
  const controls = Array.from(document.querySelectorAll(
    'button, a, [role="button"]'
  )).filter((el) => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none'
      && style.visibility !== 'hidden'
      && rect.width > 0
      && rect.height > 0;
  });
  for (const el of controls) {
    const label = clean(
      el.getAttribute('aria-label')
      || el.innerText
      || el.getAttribute('title')
      || ''
    );
    if (exactLabels.has(label)) {
      el.click();
      return true;
    }
  }
  const selectors = [
    '[data-testid*="download" i]',
    'button[aria-label*="descargar" i]',
    'button[aria-label*="download" i]',
    'a[aria-label*="descargar" i]',
    'a[aria-label*="download" i]',
    'a[download]'
  ];
  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (el) {
      el.click();
      return true;
    }
  }
  return false;
})()
"""
        return (await self._evaluate(cdp, script)) is True

    async def _click_download_when_ready(
        self,
        cdp,
        *,
        timeout_seconds: float,
    ) -> bool:
        deadline = time.monotonic() + max(0.5, float(timeout_seconds))
        while time.monotonic() < deadline:
            if await self._requires_human(cdp):
                return False
            if await self._click_download_control(cdp):
                return True
            await asyncio.sleep(0.35)
        return False

    async def _write_ui_diagnostic_async(
        self,
        cdp,
        *,
        reason: str,
    ) -> str | None:
        diagnostics_dir = self._config.browser_profile_dir.parent / "diagnostics"
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        json_path = diagnostics_dir / f"indeed-ui-review-{stamp}.json"
        png_path = diagnostics_dir / f"indeed-ui-review-{stamp}.png"

        state = await self._page_state(cdp)
        screenshot_saved = False
        if self._config.diagnostic_screenshots:
            try:
                shot = await cdp.cdp_client.send.Page.captureScreenshot(
                    params={"format": "png"},
                    session_id=cdp.session_id,
                )
                encoded = shot.get("data") if isinstance(shot, dict) else None
                if encoded:
                    png_path.write_bytes(base64.b64decode(encoded))
                    screenshot_saved = True
            except Exception:
                pass

        payload = {
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "reason": _safe_diagnostic_text(reason, limit=160),
            "url": _safe_diagnostic_url(state.get("url")),
            "title": _safe_diagnostic_text(state.get("title"), limit=300),
            "screenshot": str(png_path) if screenshot_saved else "",
            "driver": "browser-use-cdp",
            "privacy": {
                "query_strings_persisted": False,
                "cookies_persisted": False,
                "authorization_headers_persisted": False,
                "response_bodies_persisted": False,
                "screenshots_enabled": self._config.diagnostic_screenshots,
            },
        }
        try:
            json_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return str(json_path)
        except Exception:
            return None

    async def _fetch_resume_async(
        self,
        resume_url: str,
        *,
        candidate_name: str,
        job_title: str | None,
    ) -> BrowserResult:
        cdp = await self._ensure_started()
        source_url = _safe_indeed_url(resume_url)

        # Arm Network capture before navigation: a signed Indeed URL may redirect
        # directly to the attachment response without rendering a download button.
        future = self._arm_download()
        try:
            await self._navigate(cdp, source_url)
        except BrowserFetchStageError:
            raise
        except Exception as exc:
            raise BrowserFetchStageError("INDEED_NAVIGATION_FAILED") from exc

        if future.done():
            return future.result()

        if await self._requires_human(cdp):
            return BrowserResult(
                BrowserOutcome.NEEDS_HUMAN,
                human_code="INDEED_AUTH_REQUIRED",
            )

        # A direct candidate page can be a React SPA. Give the control a short
        # bounded mount window before falling back to Manage candidates.
        if await self._click_download_when_ready(cdp, timeout_seconds=3.0):
            result = await self._wait_for_download(future)
            if result is not None:
                return result

        if await self._requires_human(cdp):
            return BrowserResult(
                BrowserOutcome.NEEDS_HUMAN,
                human_code="INDEED_AUTH_REQUIRED",
            )

        error = await self._open_candidate(cdp, candidate_name, job_title)
        if error:
            diagnostic_path = await self._write_ui_diagnostic_async(
                cdp,
                reason=error,
            )
            return BrowserResult(
                BrowserOutcome.NEEDS_HUMAN,
                human_code=error,
                diagnostic_path=diagnostic_path,
            )

        if await self._requires_human(cdp):
            return BrowserResult(
                BrowserOutcome.NEEDS_HUMAN,
                human_code="INDEED_AUTH_REQUIRED",
            )

        future = self._arm_download()
        clicked = await self._click_download_when_ready(
            cdp,
            timeout_seconds=min(
                10.0,
                max(6.0, float(self._config.request_timeout_seconds)),
            ),
        )
        if not clicked:
            if await self._requires_human(cdp):
                return BrowserResult(
                    BrowserOutcome.NEEDS_HUMAN,
                    human_code="INDEED_AUTH_REQUIRED",
                )
            diagnostic_path = await self._write_ui_diagnostic_async(
                cdp,
                reason="INDEED_DOWNLOAD_CONTROL_NOT_FOUND",
            )
            return BrowserResult(
                BrowserOutcome.NEEDS_HUMAN,
                human_code="INDEED_DOWNLOAD_CONTROL_NOT_FOUND",
                diagnostic_path=diagnostic_path,
            )

        result = await self._wait_for_download(future)
        if result is not None:
            return result

        diagnostic_path = await self._write_ui_diagnostic_async(
            cdp,
            reason="INDEED_RESUME_DOWNLOAD_NOT_OBSERVED",
        )
        return BrowserResult(
            BrowserOutcome.NEEDS_HUMAN,
            human_code="INDEED_RESUME_DOWNLOAD_NOT_OBSERVED",
            diagnostic_path=diagnostic_path,
        )

    def fetch_resume(
        self,
        resume_url: str,
        *,
        candidate_name: str,
        job_title: str | None = None,
    ) -> BrowserResult:
        return self._call(
            self._fetch_resume_async(
                resume_url,
                candidate_name=candidate_name,
                job_title=job_title,
            ),
            timeout=max(
                90.0,
                float(self._config.request_timeout_seconds) * 6.0,
            ),
        )

    async def _start_diagnostic_async(self, url: str | None = None) -> None:
        self._diagnostic_events = []
        self._diagnostic_started_at = datetime.now(timezone.utc).isoformat()
        self._diagnostic_active = True
        cdp = await self._ensure_started()
        await self._navigate(cdp, _safe_indeed_url(url))
        if await self._requires_human(cdp):
            self._diagnostic_active = False
            raise RuntimeError("INDEED_MANUAL_LOGIN_REQUIRED")

    def start_diagnostic(self, url: str | None = None) -> None:
        self._call(self._start_diagnostic_async(url))

    async def _poll_diagnostic_async(self) -> None:
        if not self._diagnostic_active:
            return
        cdp = await self._ensure_started()
        if await self._requires_human(cdp):
            self._diagnostic_active = False
            raise RuntimeError("INDEED_MANUAL_LOGIN_REQUIRED")

    def poll_diagnostic(self) -> None:
        self._call(self._poll_diagnostic_async(), timeout=15.0)

    async def _stop_diagnostic_async(self) -> str | None:
        if not self._diagnostic_active:
            return self._last_diagnostic_path
        self._diagnostic_active = False
        cdp = await self._ensure_started()
        diagnostics_dir = self._config.browser_profile_dir.parent / "diagnostics"
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        json_path = diagnostics_dir / f"indeed-flow-diagnostic-{stamp}.json"
        png_path = diagnostics_dir / f"indeed-flow-diagnostic-{stamp}.png"
        state = await self._page_state(cdp)
        screenshot_saved = False
        if self._config.diagnostic_screenshots:
            try:
                shot = await cdp.cdp_client.send.Page.captureScreenshot(
                    params={"format": "png"},
                    session_id=cdp.session_id,
                )
                encoded = shot.get("data") if isinstance(shot, dict) else None
                if encoded:
                    png_path.write_bytes(base64.b64decode(encoded))
                    screenshot_saved = True
            except Exception:
                pass

        payload = {
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "started_at_utc": self._diagnostic_started_at,
            "driver": "browser-use-cdp",
            "events": list(self._diagnostic_events),
            "page": {
                "url": _safe_diagnostic_url(state.get("url")),
                "title": _safe_diagnostic_text(state.get("title"), limit=300),
            },
            "screenshot": str(png_path) if screenshot_saved else "",
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

    def stop_diagnostic(self) -> str | None:
        return self._call(self._stop_diagnostic_async(), timeout=30.0)
