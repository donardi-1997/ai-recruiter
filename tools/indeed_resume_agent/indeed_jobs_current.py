from __future__ import annotations

import asyncio
import base64
import json
import re
from types import MethodType
from urllib.parse import parse_qs, urlsplit

from . import vacancy_sync
from .browser_use_driver import _CHALLENGE_MARKERS, _URL_CHALLENGE_MARKERS


_EMPLOYER_JOB_UUID = re.compile(
    r"(?:^|/)EmployerJob/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?:$|[/?#])"
)


def _employer_job_key(raw_value: object) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""
    padded = value + ("=" * ((4 - len(value) % 4) % 4))
    try:
        decoded = base64.b64decode(padded, validate=False).decode("utf-8", errors="strict")
    except Exception:
        return ""
    match = _EMPLOYER_JOB_UUID.search(decoded)
    return str(match.group(1) if match else "").lower()


def job_key_from_current_url(raw_url: str | None) -> str:
    value = str(raw_url or "").strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
    except Exception:
        return ""
    if parsed.scheme.casefold() != "https" or str(parsed.hostname or "").casefold() != "employers.indeed.com":
        return ""

    query = parse_qs(parsed.query)
    employer_values = query.get("employerJobId") or query.get("employerjobid") or []
    if employer_values:
        key = _employer_job_key(employer_values[0])
        if key:
            return key

    return vacancy_sync._job_key_from_url_original(value) if hasattr(vacancy_sync, "_job_key_from_url_original") else ""


CURRENT_LISTING_STATE_SCRIPT = r"""
(() => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const uuidFromEmployerJobId = (value) => {
    const raw = clean(value);
    if (!raw) return '';
    try {
      const decoded = atob(raw);
      const match = decoded.match(/(?:^|\/)EmployerJob\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:$|[/?#])/i);
      return match ? String(match[1]).toLowerCase() : '';
    } catch (_) {
      return '';
    }
  };
  const jobKeyFromHref = (rawHref) => {
    const href = clean(rawHref);
    if (!href) return '';
    try {
      const url = new URL(href, location.href);
      if (url.protocol !== 'https:' || url.hostname !== 'employers.indeed.com') return '';
      const employerJobId = url.searchParams.get('employerJobId');
      const employerKey = uuidFromEmployerJobId(employerJobId);
      if (employerKey) return employerKey;
      for (const name of ['jobId', 'jobid', 'jobKey', 'jobkey', 'jk', 'id']) {
        const value = clean(url.searchParams.get(name));
        if (/^[A-Za-z0-9_-]{3,200}$/.test(value)) return value;
      }
    } catch (_) {}
    return '';
  };
  const isVisible = (node) => {
    if (!node) return false;
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.display !== 'none'
      && style.visibility !== 'hidden'
      && Number(style.opacity || '1') > 0
      && rect.width > 0
      && rect.height > 0;
  };

  const rows = [];
  const seen = new Set();
  const roots = Array.from(document.querySelectorAll('tr[data-testid="job-row"]'));
  for (const [index, root] of roots.entries()) {
    if (!isVisible(root)) continue;
    const clickable = root.querySelector(
      'a[data-testid="UnifiedJobTldLink"], [data-testid="UnifiedJobTldTitle"] a[href], a[href*="employerJobId="]'
    );
    if (!clickable || !isVisible(clickable)) continue;
    const href = clean(clickable.href || clickable.getAttribute('href') || '');
    const externalJobKey = jobKeyFromHref(href);
    const title = clean(clickable.innerText || clickable.textContent || '');
    if (!href || !externalJobKey || !title) continue;
    if (seen.has(externalJobKey)) continue;
    seen.add(externalJobKey);

    const locationNode = root.querySelector('[data-testid="UnifiedJobTldLocation"]');
    const statusNode = root.querySelector('[data-testid="top-level-job-status"]');
    const createdNode = root.querySelector('[data-testid="job-created-date"]');
    const exactDate = Array.from(createdNode?.querySelectorAll?.('[title]') || [])
      .map((node) => clean(node.getAttribute('title') || node.innerText || ''))
      .find((value) => /publicado el|posted/i.test(value)) || '';
    const rowText = clean(root.innerText || root.textContent || '');
    const absoluteY = Math.round((root.getBoundingClientRect().top || 0) + window.scrollY);
    const token = `asiati-current-job-${externalJobKey}-${index}`;
    clickable.setAttribute('data-asiati-vacancy-token', token);
    rows.push({
      externalJobKey,
      title,
      href,
      rowText,
      location: clean(locationNode?.innerText || locationNode?.textContent || ''),
      status: clean(statusNode?.innerText || statusNode?.textContent || ''),
      postedAt: exactDate,
      clickToken: token,
      rowPosition: absoluteY,
      rowIndex: index,
      listingUrl: String(location.href || ''),
      scrollY: Number(window.scrollY || 0),
    });
  }

  // Compatibility fallback for older Indeed layouts. It is deliberately
  // restricted to anchors carrying a stable provider identity.
  if (!rows.length) {
    for (const anchor of Array.from(document.querySelectorAll('a[href]'))) {
      if (!isVisible(anchor)) continue;
      const href = clean(anchor.href || anchor.getAttribute('href') || '');
      const externalJobKey = jobKeyFromHref(href);
      const title = clean(anchor.innerText || anchor.textContent || anchor.getAttribute('aria-label') || '');
      if (!externalJobKey || !title || seen.has(externalJobKey)) continue;
      seen.add(externalJobKey);
      const root = anchor.closest('tr,[role="row"],article,li') || anchor.parentElement;
      const token = `asiati-current-job-${externalJobKey}-${rows.length}`;
      anchor.setAttribute('data-asiati-vacancy-token', token);
      rows.push({
        externalJobKey,
        title,
        href,
        rowText: clean(root?.innerText || root?.textContent || title),
        location: '',
        status: '',
        postedAt: '',
        clickToken: token,
        rowPosition: Math.round((root?.getBoundingClientRect?.().top || 0) + window.scrollY),
        rowIndex: rows.length,
        listingUrl: String(location.href || ''),
        scrollY: Number(window.scrollY || 0),
      });
    }
  }

  const body = clean(document.body?.innerText || '');
  const totalMatch = body.match(/([0-9][0-9.,]*)\s+(?:resultados|results)\b/i);
  const expectedTotal = totalMatch
    ? Number(String(totalMatch[1]).replace(/[^0-9]/g, '')) || 0
    : 0;
  const nextButton = document.querySelector(
    '#ejsJobListPaginationNextBtn, button[aria-label="Siguiente"], button[aria-label="Next"]'
  );
  const hasNextPage = Boolean(
    nextButton
    && !nextButton.disabled
    && String(nextButton.getAttribute('aria-disabled') || '').toLowerCase() !== 'true'
  );
  const pageSignature = rows.map((row) => row.externalJobKey).join('|');
  return {
    url: String(location.href || ''),
    body: body.slice(0, 12000),
    rows,
    expectedTotal,
    hasNextPage,
    pageSignature,
    nextHref: '',
    scrollY: Number(window.scrollY || 0),
    previousScrollY: Number(window.scrollY || 0),
    viewportHeight: Math.max(1, Number(window.innerHeight || 1)),
    scrollHeight: Math.max(
      Number(document.documentElement?.scrollHeight || 0),
      Number(document.body?.scrollHeight || 0)
    ),
  };
})()
"""


CURRENT_PAGE_STATE_SCRIPT = r"""
(() => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none'
      && style.visibility !== 'hidden'
      && Number(style.opacity || '1') > 0
      && rect.width > 0
      && rect.height > 0;
  };
  let authStatus = '';
  let isLoggedIn = false;
  try {
    const raw = document.getElementById('one-host-bootstrap-data')?.textContent || '';
    const data = raw ? JSON.parse(raw) : {};
    authStatus = clean(data?.authState?.authStatus || '');
    isLoggedIn = Boolean(data?.passportUser?.isLoggedIn);
  } catch (_) {}
  const iframes = Array.from(document.querySelectorAll('iframe'))
    .map((el) => ({src: String(el.src || ''), visible: visible(el)}))
    .filter((row) => row.src)
    .slice(0, 50);
  return {
    url: String(location.href || ''),
    title: String(document.title || ''),
    body: clean(document.body?.innerText || '').slice(0, 12000),
    authStatus,
    isLoggedIn,
    iframes,
  };
})()
"""


async def _current_page_state(self, cdp) -> dict:
    value = await self._evaluate(cdp, CURRENT_PAGE_STATE_SCRIPT)
    return value if isinstance(value, dict) else {}


async def _current_requires_human(self, cdp) -> bool:
    state = await self._page_state(cdp)
    url = str(state.get("url") or "").casefold()
    if any(marker in url for marker in _URL_CHALLENGE_MARKERS):
        return True

    for frame in state.get("iframes") or []:
        if not isinstance(frame, dict) or not frame.get("visible"):
            continue
        candidate = str(frame.get("src") or "").casefold()
        if any(marker in candidate for marker in _URL_CHALLENGE_MARKERS):
            return True

    body = str(state.get("body") or "").casefold()
    hard_markers = (
        "captcha",
        "security challenge",
        "verify you are human",
        "verifica que eres humano",
        "mfa",
        "two-step",
        "two factor",
    )
    if any(marker in body for marker in hard_markers):
        return True

    if str(state.get("authStatus") or "").upper() == "AUTHENTICATED" or bool(state.get("isLoggedIn")):
        return False

    explicit_login = ("sign in", "log in", "iniciar sesión", "iniciar sesion")
    if any(marker in body for marker in explicit_login):
        return True
    return any(marker in body for marker in _CHALLENGE_MARKERS)


async def _listing_state(browser, cdp) -> dict:
    value = await browser._evaluate(cdp, CURRENT_LISTING_STATE_SCRIPT)
    return value if isinstance(value, dict) else {"rows": [], "expectedTotal": 0, "hasNextPage": False}


async def _advance_page(browser, cdp, previous_signature: str) -> bool:
    clicked = bool(
        await browser._evaluate(
            cdp,
            r"""
(() => {
  const button = document.querySelector(
    '#ejsJobListPaginationNextBtn, button[aria-label="Siguiente"], button[aria-label="Next"]'
  );
  if (!button || button.disabled || String(button.getAttribute('aria-disabled') || '').toLowerCase() === 'true') {
    return false;
  }
  button.click();
  return true;
})()
""",
        )
    )
    if not clicked:
        return False

    deadline = asyncio.get_running_loop().time() + max(
        8.0,
        float(browser._config.request_timeout_seconds),
    )
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.2)
        if await browser._requires_human(cdp):
            raise RuntimeError("INDEED_AUTH_REQUIRED")
        state = await _listing_state(browser, cdp)
        signature = str(state.get("pageSignature") or "")
        if signature and signature != previous_signature and state.get("rows"):
            return True
    return False


async def _collect_current_jobs(browser) -> list[dict]:
    cdp = await browser._ensure_started()
    await browser._navigate(cdp, vacancy_sync.INDEED_JOBS_URL)
    if await browser._requires_human(cdp):
        raise RuntimeError("INDEED_AUTH_REQUIRED")

    discovered: dict[str, dict] = {}
    expected_total = 0
    state: dict = {}

    for page_index in range(50):
        # Wait for the React job table to hydrate. A loaded workspace with zero
        # rows is not treated as a successful empty sync when Indeed reports a total.
        deadline = asyncio.get_running_loop().time() + max(
            12.0,
            float(browser._config.request_timeout_seconds),
        )
        while asyncio.get_running_loop().time() < deadline:
            state = await _listing_state(browser, cdp)
            expected_total = max(expected_total, int(state.get("expectedTotal") or 0))
            if state.get("rows"):
                break
            await asyncio.sleep(0.25)
        rows = state.get("rows") or []
        if not rows:
            raise RuntimeError("INDEED_JOB_LIST_NOT_READY")

        for row in rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get("externalJobKey") or "").strip().lower()
            href = vacancy_sync._safe_job_url(row.get("href"))
            title = " ".join(str(row.get("title") or "").split()).strip()
            if not key or not href or not title:
                raise RuntimeError("INDEED_JOB_SYNC_INCOMPLETE")
            normalized = dict(row)
            normalized["externalJobKey"] = key[:200]
            normalized["href"] = href
            normalized["title"] = title
            discovered[key[:200]] = normalized

        if not state.get("hasNextPage"):
            break
        if page_index >= 49:
            raise RuntimeError("INDEED_JOB_LIST_INCOMPLETE")
        signature = str(state.get("pageSignature") or "")
        if not signature or not await _advance_page(browser, cdp, signature):
            raise RuntimeError("INDEED_JOB_LIST_INCOMPLETE")

    if expected_total and len(discovered) < expected_total:
        raise RuntimeError("INDEED_JOB_LIST_INCOMPLETE")

    snapshots: dict[str, dict] = {}
    for key, row in discovered.items():
        href = vacancy_sync._safe_job_url(row.get("href"))
        await browser._navigate(cdp, href)
        if await browser._requires_human(cdp):
            raise RuntimeError("INDEED_AUTH_REQUIRED")
        detail = await vacancy_sync._wait_for_detail(browser, cdp, row["title"])
        detail_title = " ".join(str(detail.get("title") or row["title"]).split()).strip()
        if not detail_title:
            raise RuntimeError("INDEED_JOB_SYNC_INCOMPLETE")
        snapshots[key] = {
            "external_job_key": key,
            "title": detail_title,
            "description": str(detail.get("description") or "").strip(),
            "status": str(detail.get("status") or row.get("status") or "").strip() or None,
            "location": str(detail.get("location") or row.get("location") or "").strip() or None,
            "posted_at": str(detail.get("postedAt") or row.get("postedAt") or "").strip() or None,
        }

    return list(snapshots.values())


def install_current_indeed_jobs(browser) -> None:
    """Install compatibility for the current Indeed Employers jobs workspace.

    This layer is grounded in the production DOM: UnifiedJobTldLink,
    employerJobId and button-based pagination. It is intentionally installed
    last so older compatibility shims remain as testable fallbacks but cannot
    override the current production contract.
    """

    if not hasattr(vacancy_sync, "_job_key_from_url_original"):
        vacancy_sync._job_key_from_url_original = vacancy_sync._job_key_from_url

    original = vacancy_sync._job_key_from_url_original

    def current_parser(raw_url: str | None) -> str:
        value = str(raw_url or "").strip()
        if not value:
            return ""
        try:
            parsed = urlsplit(value)
        except Exception:
            return ""
        if parsed.scheme.casefold() != "https" or str(parsed.hostname or "").casefold() != "employers.indeed.com":
            return ""
        query = parse_qs(parsed.query)
        values = query.get("employerJobId") or query.get("employerjobid") or []
        if values:
            key = _employer_job_key(values[0])
            if key:
                return key
        return original(value)

    browser._page_state = MethodType(_current_page_state, browser)
    browser._requires_human = MethodType(_current_requires_human, browser)
    vacancy_sync._job_key_from_url = current_parser
    vacancy_sync.LISTING_STATE_SCRIPT = CURRENT_LISTING_STATE_SCRIPT
    vacancy_sync._collect_async = _collect_current_jobs
