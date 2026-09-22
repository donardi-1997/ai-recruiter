from __future__ import annotations

import asyncio
import re
from urllib.parse import parse_qs, urljoin, urlsplit


INDEED_JOBS_URL = (
    "https://employers.indeed.com/jobs?status=open%2Cpaused&claimed=false&"
    "createdOnIndeed=true&tab=0&sortDirection=DESC&sortField=datePostedOnIndeed"
)

_QUERY_ID_KEYS = ("jobId", "jobid", "id", "jk", "jobKey", "jobkey")
_PATH_JOB_ID = re.compile(r"/(?:jobs?|job)/(?:view/)?([A-Za-z0-9_-]{3,200})(?:/|$)")


def _job_key_from_url(raw_url: str | None) -> str:
    value = str(raw_url or "").strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
    except Exception:
        return ""
    host = str(parsed.hostname or "").casefold()
    if parsed.scheme.casefold() != "https" or host != "employers.indeed.com":
        return ""
    query = parse_qs(parsed.query)
    for key in _QUERY_ID_KEYS:
        values = query.get(key) or []
        candidate = str(values[0] if values else "").strip()
        if candidate:
            return candidate[:200]
    match = _PATH_JOB_ID.search(str(parsed.path or ""))
    if not match:
        return ""
    candidate = str(match.group(1) or "").strip()
    if candidate.casefold() in {"view", "open", "paused", "create", "new"}:
        return ""
    return candidate[:200]


def _safe_job_url(raw_url: str | None) -> str:
    value = str(raw_url or "").strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
    except Exception:
        return ""
    if parsed.scheme.casefold() != "https" or str(parsed.hostname or "").casefold() != "employers.indeed.com":
        return ""
    return value


async def _listing_state(browser, cdp) -> dict:
    script = r"""
(async () => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const anchors = Array.from(document.querySelectorAll('a[href]'));
  const rows = [];
  const seen = new Set();
  for (const anchor of anchors) {
    const href = String(anchor.href || '');
    if (!href.includes('employers.indeed.com')) continue;
    if (!(/\/jobs?\//.test(href) || /[?&](?:jobId|jobid|id|jk|jobKey)=/i.test(href))) continue;
    const card = anchor.closest('[data-testid*="job" i], tr, li, article') || anchor.parentElement;
    const title = clean(
      anchor.getAttribute('aria-label')
      || anchor.innerText
      || card?.querySelector?.('h1,h2,h3,[data-testid*="title" i]')?.innerText
      || ''
    );
    const rowText = clean(card?.innerText || anchor.innerText || '');
    const key = href + '|' + title;
    if (!href || seen.has(key)) continue;
    seen.add(key);
    rows.push({href, title, rowText});
  }

  let nextHref = '';
  const nextCandidates = [
    'a[rel="next"][href]',
    'a[aria-label*="next" i][href]',
    'a[aria-label*="siguiente" i][href]',
    'a[data-testid*="next" i][href]'
  ];
  for (const selector of nextCandidates) {
    const next = document.querySelector(selector);
    if (next?.href) { nextHref = String(next.href); break; }
  }

  window.scrollTo(0, document.body?.scrollHeight || 0);
  await new Promise((resolve) => setTimeout(resolve, 350));
  return {rows, nextHref};
})()
"""
    value = await browser._evaluate(cdp, script)
    return value if isinstance(value, dict) else {"rows": [], "nextHref": ""}


async def _detail_state(browser, cdp) -> dict:
    script = r"""
(() => {
  const oneLine = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const multiLine = (v) => String(v || '')
    .replace(/\r/g, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  const firstText = (selectors, multiline = false) => {
    for (const selector of selectors) {
      const nodes = Array.from(document.querySelectorAll(selector));
      for (const node of nodes) {
        const text = multiline ? multiLine(node.innerText || '') : oneLine(node.innerText || '');
        if (text) return text;
      }
    }
    return '';
  };
  const descriptionSelectors = [
    '[data-testid="job-description"]',
    '[data-testid*="job-description" i]',
    '[data-testid*="description" i]',
    '#jobDescriptionText',
    '[class*="jobDescription"]',
    '[class*="job-description"]',
    '[aria-label*="job description" i]',
    '[aria-label*="descripción" i]'
  ];
  const descriptionCandidates = [];
  for (const selector of descriptionSelectors) {
    for (const node of document.querySelectorAll(selector)) {
      const text = multiLine(node.innerText || '');
      if (text.length >= 20) descriptionCandidates.push(text);
    }
  }
  descriptionCandidates.sort((a, b) => b.length - a.length);
  const title = firstText([
    '[data-testid*="job-title" i]',
    'h1',
    '[role="heading"][aria-level="1"]'
  ]);
  const location = firstText([
    '[data-testid*="location" i]',
    '[class*="location" i]'
  ]);
  const status = firstText([
    '[data-testid*="status" i]',
    '[aria-label*="status" i]',
    '[aria-label*="estado" i]'
  ]);
  const time = document.querySelector('time[datetime]');
  return {
    url: location.href,
    title,
    description: descriptionCandidates[0] || '',
    location,
    status,
    postedAt: String(time?.getAttribute?.('datetime') || '')
  };
})()
"""
    value = await browser._evaluate(cdp, script)
    return value if isinstance(value, dict) else {}


async def _collect_async(browser) -> list[dict]:
    cdp = await browser._ensure_started()
    await browser._navigate(cdp, INDEED_JOBS_URL)
    if await browser._requires_human(cdp):
        raise RuntimeError("INDEED_AUTH_REQUIRED")

    rows_by_url: dict[str, dict] = {}
    page_url = INDEED_JOBS_URL
    visited_pages: set[str] = set()

    for _page_index in range(50):
        if page_url in visited_pages:
            break
        visited_pages.add(page_url)
        if page_url != INDEED_JOBS_URL:
            await browser._navigate(cdp, page_url)
            if await browser._requires_human(cdp):
                raise RuntimeError("INDEED_AUTH_REQUIRED")

        stable_rounds = 0
        previous_count = -1
        latest_next = ""
        for _ in range(8):
            state = await _listing_state(browser, cdp)
            for row in state.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                href = _safe_job_url(row.get("href"))
                if not href or not _job_key_from_url(href):
                    continue
                rows_by_url[href] = dict(row)
            latest_next = _safe_job_url(state.get("nextHref"))
            if len(rows_by_url) == previous_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                previous_count = len(rows_by_url)
            if stable_rounds >= 2:
                break
            await asyncio.sleep(0.15)

        if not latest_next or latest_next in visited_pages:
            break
        page_url = latest_next

    snapshots: list[dict] = []
    for href, row in rows_by_url.items():
        await browser._navigate(cdp, href)
        if await browser._requires_human(cdp):
            raise RuntimeError("INDEED_AUTH_REQUIRED")
        detail = await _detail_state(browser, cdp)
        detail_url = _safe_job_url(detail.get("url")) or href
        external_job_key = _job_key_from_url(detail_url) or _job_key_from_url(href)
        title = " ".join(str(detail.get("title") or row.get("title") or "").split()).strip()
        description = str(detail.get("description") or "").strip()
        if not title:
            continue
        snapshots.append(
            {
                "external_job_key": external_job_key,
                "title": title,
                "description": description,
                "status": str(detail.get("status") or "").strip() or None,
                "location": str(detail.get("location") or "").strip() or None,
                "posted_at": str(detail.get("postedAt") or "").strip() or None,
            }
        )

    return snapshots


def collect_vacancy_snapshots(browser) -> list[dict]:
    """Collect normalized job snapshots through the already-owned Browser Use session."""
    return browser._call(
        _collect_async(browser),
        timeout=max(
            180.0,
            float(browser._config.request_timeout_seconds) * 20.0,
        ),
    )
