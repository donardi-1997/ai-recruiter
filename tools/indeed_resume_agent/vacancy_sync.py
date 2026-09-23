from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import parse_qs, urlsplit


INDEED_JOBS_URL = (
    "https://employers.indeed.com/jobs?status=open%2Cpaused&claimed=false&"
    "createdOnIndeed=true&tab=0&sortDirection=DESC&sortField=datePostedOnIndeed"
)

_QUERY_ID_KEYS = ("jobId", "jobid", "id", "jk", "jobKey", "jobkey")
_PATH_JOB_ID = re.compile(r"/(?:jobs?|job)/(?:view/)?([A-Za-z0-9_-]{3,200})(?:/|$)")


LISTING_STATE_SCRIPT = r"""
(async () => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const validKey = (v) => /^[A-Za-z0-9_-]{3,200}$/.test(String(v || '').trim());
  const jobKeyFromHref = (rawHref) => {
    const href = String(rawHref || '').trim();
    if (!href) return '';
    try {
      const url = new URL(href, location.href);
      if (String(url.hostname || '').toLowerCase() !== 'employers.indeed.com') return '';
      for (const key of ['jobId', 'jobid', 'id', 'jk', 'jobKey', 'jobkey']) {
        const value = clean(url.searchParams.get(key));
        if (validKey(value)) return value;
      }
      const match = String(url.pathname || '').match(/\/(?:jobs?|job)\/(?:view\/)?([A-Za-z0-9_-]{3,200})(?:\/|$)/i);
      if (match && validKey(match[1]) && !['view', 'open', 'paused', 'create', 'new'].includes(match[1].toLowerCase())) {
        return match[1];
      }
    } catch (_) {}
    return '';
  };
  const jobKeyFromElement = (element) => {
    if (!element) return '';
    const nodes = [element, ...Array.from(element.querySelectorAll?.('*') || [])];
    for (const node of nodes) {
      if (node.href) {
        const hrefKey = jobKeyFromHref(node.href);
        if (hrefKey) return hrefKey;
      }
      for (const attr of Array.from(node.attributes || [])) {
        const name = String(attr.name || '').toLowerCase();
        const value = clean(attr.value);
        const looksLikeJobIdentity = name.includes('job') && (name.includes('id') || name.includes('key'));
        if (looksLikeJobIdentity && validKey(value)) return value;
      }
    }
    return '';
  };
  const ignoredClickable = /^(todos|nuevos|patrocinar empleo|abierto|pausado|cerrado|más|more)$/i;
  const chooseClickable = (root) => {
    const preferred = Array.from(root.querySelectorAll(
      '[data-testid*="title" i], a, button[role="link"], [role="link"], button'
    ));
    for (const node of preferred) {
      const text = clean(node.getAttribute?.('aria-label') || node.innerText || '');
      if (!text || text.length < 3 || ignoredClickable.test(text)) continue;
      return node;
    }
    return null;
  };

  const roots = Array.from(new Set([
    ...document.querySelectorAll('tr'),
    ...document.querySelectorAll('[role="row"]'),
    ...document.querySelectorAll('[data-testid*="job" i]'),
    ...document.querySelectorAll('article'),
    ...document.querySelectorAll('li')
  ]));
  const rows = [];
  const seen = new Set();
  let tokenCounter = 0;

  for (const root of roots) {
    const clickable = chooseClickable(root);
    if (!clickable) continue;
    const href = String(clickable.href || '');
    const externalJobKey = jobKeyFromHref(href) || jobKeyFromElement(root);
    const title = clean(
      clickable.getAttribute?.('aria-label')
      || clickable.innerText
      || root.querySelector?.('h1,h2,h3,[data-testid*="title" i]')?.innerText
      || ''
    );
    if (!title) continue;
    const rowText = clean(root.innerText || '');
    const dedupeKey = externalJobKey
      ? `stable|${externalJobKey}`
      : `pending|${title}|${rowText}`;
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);
    const clickToken = `asiati-vacancy-${Date.now()}-${tokenCounter++}`;
    clickable.setAttribute('data-asiati-vacancy-token', clickToken);
    rows.push({
      href,
      title,
      rowText,
      externalJobKey,
      clickToken,
      scrollY: Number(window.scrollY || 0),
      listingUrl: String(window.location.href || '')
    });
  }

  // Preserve the classic Indeed workspace shape where a useful job anchor is
  // not wrapped by one of the row-like containers above.
  for (const anchor of Array.from(document.querySelectorAll('a[href]'))) {
    const href = String(anchor.href || '');
    const externalJobKey = jobKeyFromHref(href);
    if (!externalJobKey) continue;
    const title = clean(anchor.getAttribute('aria-label') || anchor.innerText || '');
    if (!title) continue;
    const dedupeKey = `stable|${externalJobKey}`;
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);
    const clickToken = `asiati-vacancy-${Date.now()}-${tokenCounter++}`;
    anchor.setAttribute('data-asiati-vacancy-token', clickToken);
    rows.push({
      href,
      title,
      rowText: clean(anchor.closest('tr,li,article,[role="row"]')?.innerText || anchor.innerText || ''),
      externalJobKey,
      clickToken,
      scrollY: Number(window.scrollY || 0),
      listingUrl: String(window.location.href || '')
    });
  }

  let nextHref = '';
  for (const selector of [
    'a[rel="next"][href]',
    'a[aria-label*="next" i][href]',
    'a[aria-label*="siguiente" i][href]',
    'a[data-testid*="next" i][href]'
  ]) {
    const next = document.querySelector(selector);
    if (next?.href) { nextHref = String(next.href); break; }
  }

  const before = Number(window.scrollY || 0);
  const viewport = Math.max(Number(window.innerHeight || 0), 500);
  window.scrollBy(0, Math.max(420, Math.floor(viewport * 0.82)));
  await new Promise((resolve) => setTimeout(resolve, 300));
  return {
    rows,
    nextHref,
    scrollY: Number(window.scrollY || 0),
    previousScrollY: before,
    scrollHeight: Number(document.documentElement?.scrollHeight || document.body?.scrollHeight || 0),
    viewportHeight: viewport
  };
})()
"""


DETAIL_STATE_SCRIPT = r"""
(() => {
  const oneLine = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const multiLine = (v) => String(v || '')
    .replace(/\r/g, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  const validKey = (v) => /^[A-Za-z0-9_-]{3,200}$/.test(String(v || '').trim());
  const jobKeyFromHref = (rawHref) => {
    const href = String(rawHref || '').trim();
    if (!href) return '';
    try {
      const url = new URL(href, location.href);
      if (String(url.hostname || '').toLowerCase() !== 'employers.indeed.com') return '';
      for (const key of ['jobId', 'jobid', 'id', 'jk', 'jobKey', 'jobkey']) {
        const value = oneLine(url.searchParams.get(key));
        if (validKey(value)) return value;
      }
      const match = String(url.pathname || '').match(/\/(?:jobs?|job)\/(?:view\/)?([A-Za-z0-9_-]{3,200})(?:\/|$)/i);
      if (match && validKey(match[1]) && !['view', 'open', 'paused', 'create', 'new'].includes(match[1].toLowerCase())) {
        return match[1];
      }
    } catch (_) {}
    return '';
  };
  const jobKeyFromElement = (element) => {
    if (!element) return '';
    const nodes = [element, ...Array.from(element.querySelectorAll?.('*') || [])];
    for (const node of nodes) {
      if (node.href) {
        const hrefKey = jobKeyFromHref(node.href);
        if (hrefKey) return hrefKey;
      }
      for (const attr of Array.from(node.attributes || [])) {
        const name = String(attr.name || '').toLowerCase();
        const value = oneLine(attr.value);
        const looksLikeJobIdentity = name.includes('job') && (name.includes('id') || name.includes('key'));
        if (looksLikeJobIdentity && validKey(value)) return value;
      }
    }
    return '';
  };
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
  const pageText = oneLine(document.body?.innerText || '').toLowerCase();
  const loading = [
    'cargando los detalles del empleo',
    'cargando detalles del empleo',
    'loading job details',
    'loading the job details'
  ].some((marker) => pageText.includes(marker));
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
    '[role="dialog"] h1',
    '[role="dialog"] [role="heading"][aria-level="1"]',
    'main h1',
    'h1',
    '[role="heading"][aria-level="1"]'
  ]);
  const locationText = firstText([
    '[data-testid*="location" i]',
    '[class*="location" i]'
  ]);
  const status = firstText([
    '[data-testid*="status" i]',
    '[aria-label*="status" i]',
    '[aria-label*="estado" i]'
  ]);
  const detailRoot = document.querySelector('[role="dialog"], [data-testid*="job-detail" i], main') || document.body;
  const externalJobKey = jobKeyFromHref(window.location.href) || jobKeyFromElement(detailRoot);
  const time = document.querySelector('time[datetime]');
  return {
    url: window.location.href,
    externalJobKey,
    title,
    description: descriptionCandidates[0] || '',
    location: locationText,
    status,
    postedAt: String(time?.getAttribute?.('datetime') || ''),
    loading
  };
})()
"""


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


def _normalized_discovery_text(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


async def _listing_state(browser, cdp) -> dict:
    value = await browser._evaluate(cdp, LISTING_STATE_SCRIPT)
    return value if isinstance(value, dict) else {"rows": [], "nextHref": ""}


async def _detail_state(browser, cdp) -> dict:
    value = await browser._evaluate(cdp, DETAIL_STATE_SCRIPT)
    return value if isinstance(value, dict) else {}


async def _wait_for_detail(browser, cdp, expected_title: str) -> dict:
    normalized_expected = _normalized_discovery_text(expected_title)
    last_state: dict = {}
    deadline = asyncio.get_running_loop().time() + max(
        8.0,
        float(browser._config.request_timeout_seconds),
    )
    while asyncio.get_running_loop().time() < deadline:
        last_state = await _detail_state(browser, cdp)
        if not last_state.get("loading"):
            title = _normalized_discovery_text(last_state.get("title"))
            has_expected_title = bool(normalized_expected and normalized_expected in title)
            has_description = bool(str(last_state.get("description") or "").strip())
            if has_expected_title or has_description:
                return last_state
        await asyncio.sleep(0.2)
    return last_state


async def _click_listing_row(browser, cdp, row: dict) -> bool:
    token = str(row.get("clickToken") or "").strip()
    external_job_key = str(row.get("externalJobKey") or "").strip()
    title = " ".join(str(row.get("title") or "").split()).strip()
    scroll_y = max(0, int(row.get("scrollY") or 0))
    await browser._evaluate(
        cdp,
        f"window.scrollTo(0, {scroll_y}); true",
    )
    await asyncio.sleep(0.18)
    payload = json.dumps(
        {"token": token, "externalJobKey": external_job_key, "title": title},
        ensure_ascii=False,
    )
    script = f"""
(() => {{
  const target = {payload};
  const clean = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
  const byToken = target.token
    ? document.querySelector(`[data-asiati-vacancy-token="${{CSS.escape(target.token)}}"]`)
    : null;
  if (byToken) {{ byToken.click(); return true; }}

  const identityAttrs = ['data-job-id','data-jobid','data-job-key','data-jobkey','data-indeed-job-id','data-indeed-job-key'];
  for (const attr of identityAttrs) {{
    const escaped = CSS.escape(target.externalJobKey || '');
    const root = escaped ? document.querySelector(`[${{attr}}="${{escaped}}"]`) : null;
    if (!root) continue;
    const clickable = root.matches('a,button,[role="link"]')
      ? root
      : root.querySelector('a,button,[role="link"]');
    if (clickable) {{ clickable.click(); return true; }}
  }}

  const candidates = Array.from(document.querySelectorAll('a,button,[role="link"]'))
    .filter((node) => clean(node.getAttribute?.('aria-label') || node.innerText || '') === target.title);
  if (candidates.length === 1) {{ candidates[0].click(); return true; }}
  return false;
}})()
"""
    return bool(await browser._evaluate(cdp, script))


async def _close_spa_detail(browser, cdp) -> bool:
    script = r"""
(() => {
  const selectors = [
    'button[aria-label*="close" i]',
    'button[aria-label*="cerrar" i]',
    '[data-testid*="close" i]'
  ];
  for (const selector of selectors) {
    const candidate = document.querySelector(selector);
    if (!candidate) continue;
    candidate.click();
    return true;
  }
  return false;
})()
"""
    closed = bool(await browser._evaluate(cdp, script))
    if closed:
        await asyncio.sleep(0.2)
    return closed


async def _collect_async(browser) -> list[dict]:
    cdp = await browser._ensure_started()
    await browser._navigate(cdp, INDEED_JOBS_URL)
    if await browser._requires_human(cdp):
        raise RuntimeError("INDEED_AUTH_REQUIRED")

    rows_by_key: dict[str, dict] = {}
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
        for _ in range(60):
            state = await _listing_state(browser, cdp)
            for row in state.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                href = _safe_job_url(row.get("href"))
                external_job_key = str(row.get("externalJobKey") or "").strip()
                if not external_job_key:
                    external_job_key = _job_key_from_url(href)
                title = " ".join(str(row.get("title") or "").split()).strip()
                if not title:
                    continue
                row_text = " ".join(str(row.get("rowText") or "").split()).strip()
                normalized = dict(row)
                normalized["href"] = href
                normalized["title"] = title
                normalized["rowText"] = row_text
                normalized["externalJobKey"] = external_job_key[:200]
                normalized["listingUrl"] = _safe_job_url(row.get("listingUrl")) or page_url
                if external_job_key:
                    discovery_key = f"stable:{external_job_key[:200]}"
                else:
                    click_token = str(row.get("clickToken") or "").strip()
                    if click_token:
                        discovery_key = (
                            "pending-token:"
                            f"{normalized['listingUrl']}|{click_token}"
                        )
                    else:
                        discovery_key = (
                            "pending:"
                            f"{_normalized_discovery_text(title)}|"
                            f"{_normalized_discovery_text(row_text)}"
                        )
                rows_by_key[discovery_key] = normalized

            latest_next = _safe_job_url(state.get("nextHref"))
            current_count = len(rows_by_key)
            at_bottom = (
                int(state.get("scrollY") or 0) + int(state.get("viewportHeight") or 0)
                >= max(0, int(state.get("scrollHeight") or 0) - 8)
            )
            if current_count == previous_count and at_bottom:
                stable_rounds += 1
            else:
                stable_rounds = 0
                previous_count = current_count
            if stable_rounds >= 3:
                break
            await asyncio.sleep(0.12)

        if not latest_next or latest_next in visited_pages:
            break
        page_url = latest_next

    snapshots_by_key: dict[str, dict] = {}
    current_listing_url = ""
    for row in rows_by_key.values():
        href = _safe_job_url(row.get("href"))
        expected_title = " ".join(str(row.get("title") or "").split()).strip()
        listing_url = _safe_job_url(row.get("listingUrl")) or INDEED_JOBS_URL
        external_job_key = str(row.get("externalJobKey") or "").strip()
        used_spa_click = False

        if href and _job_key_from_url(href):
            await browser._navigate(cdp, href)
            current_listing_url = ""
        else:
            if current_listing_url != listing_url:
                await browser._navigate(cdp, listing_url)
                current_listing_url = listing_url
                if await browser._requires_human(cdp):
                    raise RuntimeError("INDEED_AUTH_REQUIRED")
            used_spa_click = await _click_listing_row(browser, cdp, row)
            if not used_spa_click:
                continue

        if await browser._requires_human(cdp):
            raise RuntimeError("INDEED_AUTH_REQUIRED")
        detail = await _wait_for_detail(browser, cdp, expected_title)
        detail_url = _safe_job_url(detail.get("url")) or href
        detail_job_key = str(detail.get("externalJobKey") or "").strip()
        stable_key = _job_key_from_url(detail_url) or detail_job_key or external_job_key
        title = " ".join(str(detail.get("title") or expected_title).split()).strip()
        description = str(detail.get("description") or "").strip()
        if stable_key and title:
            snapshots_by_key[stable_key[:200]] = {
                "external_job_key": stable_key[:200],
                "title": title,
                "description": description,
                "status": str(detail.get("status") or "").strip() or None,
                "location": str(detail.get("location") or "").strip() or None,
                "posted_at": str(detail.get("postedAt") or "").strip() or None,
            }

        if used_spa_click:
            if not await _close_spa_detail(browser, cdp):
                await browser._navigate(cdp, listing_url)
            current_listing_url = listing_url
        else:
            await browser._navigate(cdp, listing_url)
            current_listing_url = listing_url

    return list(snapshots_by_key.values())


def collect_vacancy_snapshots(browser) -> list[dict]:
    """Collect normalized job snapshots through the already-owned Browser Use session."""
    return browser._call(
        _collect_async(browser),
        timeout=max(
            1800.0,
            float(browser._config.request_timeout_seconds) * 60.0,
        ),
    )