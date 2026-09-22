from __future__ import annotations

from types import MethodType

from . import vacancy_sync
from .browser_use_driver import _CHALLENGE_MARKERS, _URL_CHALLENGE_MARKERS


SAFE_LISTING_STATE_SCRIPT = r"""
(() => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const lower = (v) => clean(v).toLowerCase();
  const ignoredLabels = new Set([
    '', 'todos', 'nuevos', 'all', 'new', 'abierto', 'pausado', 'open', 'paused',
    'patrocinar empleo', 'sponsor job', 'ver empleos', 'view jobs',
    'más opciones', 'mas opciones', 'more options'
  ]);

  const jobKeyFromHref = (href) => {
    try {
      const url = new URL(String(href || ''), location.href);
      if (url.protocol !== 'https:' || url.hostname !== 'employers.indeed.com') return '';
      for (const name of ['jobId', 'jobID', 'jobKey', 'id']) {
        const value = clean(url.searchParams.get(name));
        if (value) return value;
      }
      const parts = url.pathname.split('/').filter(Boolean);
      const jobsIndex = parts.indexOf('jobs');
      if (jobsIndex >= 0 && parts.length > jobsIndex + 1) {
        const tail = clean(parts[parts.length - 1]);
        if (tail && !['view', 'details', 'edit', 'jobs'].includes(tail.toLowerCase())) return tail;
      }
    } catch (_) {}
    return '';
  };

  const jobKeyFromElement = (root) => {
    if (!root) return '';
    const attrs = [
      'data-job-id', 'data-jobid', 'data-job-key', 'data-jobkey',
      'data-id', 'data-key', 'data-indeed-job-id'
    ];
    let cursor = root;
    for (let depth = 0; cursor && depth < 4; depth += 1, cursor = cursor.parentElement) {
      for (const attr of attrs) {
        const value = clean(cursor.getAttribute?.(attr));
        if (value) return value;
      }
    }
    for (const node of root.querySelectorAll?.('[data-job-id],[data-jobid],[data-job-key],[data-jobkey]') || []) {
      for (const attr of attrs) {
        const value = clean(node.getAttribute?.(attr));
        if (value) return value;
      }
    }
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

  const isSafeEmployerHref = (href, root) => {
    if (!href) return true;
    try {
      const url = new URL(String(href), location.href);
      if (url.protocol !== 'https:' || url.hostname !== 'employers.indeed.com') return false;
      return Boolean(jobKeyFromHref(url.href) || jobKeyFromElement(root));
    } catch (_) {
      return false;
    }
  };

  const chooseClickable = (root) => {
    const selectors = [
      '[data-testid*="title" i]',
      'button[role="link"]',
      '[role="link"]',
      'a[href]',
      'button'
    ];
    for (const selector of selectors) {
      for (const node of root.querySelectorAll?.(selector) || []) {
        if (!isVisible(node)) continue;
        const label = lower(node.getAttribute?.('aria-label') || node.innerText || node.textContent || '');
        if (ignoredLabels.has(label)) continue;
        const href = clean(node.href || node.getAttribute?.('href') || '');
        if (!isSafeEmployerHref(href, root)) continue;
        return node;
      }
    }
    return null;
  };

  const looksLikeJobContainer = (node) => {
    if (!node || !isVisible(node)) return false;
    const text = lower(node.innerText || node.textContent || '');
    const hasStatus = /\b(abierto|pausado|open|paused)\b/i.test(text);
    const hasCandidateCounts = /\b(candidatos|todos|nuevos|candidates|all|new)\b/i.test(text);
    return hasStatus && hasCandidateCounts && Boolean(chooseClickable(node));
  };

  const roots = [];
  const seenRoots = new Set();
  const addRoot = (node) => {
    if (!node || seenRoots.has(node) || !isVisible(node)) return;
    seenRoots.add(node);
    roots.push(node);
  };

  // Current Indeed Employers renders vacancies as table/ARIA rows, job-labelled
  // containers, or list/article cards. List/article nodes without a stable
  // provider id are accepted only when they expose both vacancy-status and
  // candidate-count signals plus a safe clickable title. This keeps footer,
  // legal and navigation entries out while allowing SPA cards whose id only
  // appears after opening the detail panel.
  for (const selector of ['tr', '[role="row"]', '[data-testid*="job" i]']) {
    for (const node of document.querySelectorAll(selector)) addRoot(node);
  }
  for (const node of document.querySelectorAll('article, li')) {
    if (jobKeyFromElement(node) || looksLikeJobContainer(node)) addRoot(node);
  }

  const rows = [];
  const seen = new Set();
  let clickIndex = 0;
  for (const root of roots.slice(0, 500)) {
    const rowText = clean(root.innerText || root.textContent || '');
    if (!rowText) continue;

    let externalJobKey = jobKeyFromElement(root);
    const clickable = chooseClickable(root);
    if (!clickable) continue;
    const href = clean(clickable.href || clickable.getAttribute?.('href') || '');
    if (!externalJobKey && href) externalJobKey = jobKeyFromHref(href);

    const title = clean(
      clickable.innerText
      || clickable.textContent
      || clickable.getAttribute?.('aria-label')
      || ''
    );
    if (!title || ignoredLabels.has(title.toLowerCase())) continue;

    if (!externalJobKey) {
      const text = rowText.toLowerCase();
      const hasStatus = /\b(abierto|pausado|open|paused)\b/i.test(text);
      const hasCandidateCounts = /\b(candidatos|todos|nuevos|candidates|all|new)\b/i.test(text);
      if (!(hasStatus && hasCandidateCounts)) continue;
    }

    const dedupeKey = externalJobKey
      ? `job:${externalJobKey}`
      : `pending:${title}|${rowText}`;
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);

    const token = `asiati-job-${clickIndex++}`;
    clickable.setAttribute('data-asiati-job-token', token);
    rows.push({
      externalJobKey,
      title,
      href,
      rowText,
      clickToken: token,
    });
  }

  return {
    url: location.href,
    body: clean(document.body?.innerText || '').slice(0, 12000),
    rows,
  };
})()
"""


async def _visible_page_state(self, cdp) -> dict:
    script = r"""
(() => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none'
      && style.visibility !== 'hidden'
      && Number(style.opacity || '1') > 0
      && rect.width > 0
      && rect.height > 0;
  };
  const iframes = Array.from(document.querySelectorAll('iframe'))
    .map((el) => ({src: String(el.src || ''), visible: visible(el)}))
    .filter((row) => row.src)
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


async def _visibility_aware_requires_human(self, cdp) -> bool:
    state = await self._page_state(cdp)
    url = str(state.get("url") or "").casefold()
    if any(marker in url for marker in _URL_CHALLENGE_MARKERS):
        return True

    for frame in state.get("iframes") or []:
        if isinstance(frame, dict):
            if not frame.get("visible"):
                continue
            candidate = str(frame.get("src") or "").casefold()
        else:
            # Backward-compatible handling for test/diagnostic snapshots made
            # before iframe visibility was captured.
            candidate = str(frame or "").casefold()
        if any(marker in candidate for marker in _URL_CHALLENGE_MARKERS):
            return True

    body = str(state.get("body") or "").casefold()
    hard_body_markers = (
        "captcha",
        "security challenge",
        "verify you are human",
        "verifica que eres humano",
        "mfa",
        "two-step",
        "two factor",
    )
    if any(marker in body for marker in hard_body_markers):
        return True

    title = str(state.get("title") or "").casefold()
    on_jobs_workspace = url.startswith("https://employers.indeed.com/jobs")
    has_jobs_identity = "indeed" in title and ("empleos" in title or "jobs" in title)
    has_jobs_controls = (
        ("publicar un empleo" in body and "todos los empleos" in body)
        or ("post a job" in body and "all jobs" in body)
    )
    if on_jobs_workspace and has_jobs_identity and has_jobs_controls:
        return False

    return any(marker in body for marker in _CHALLENGE_MARKERS)


def install_runtime_compat(browser) -> None:
    """Apply narrowly scoped Indeed UI compatibility without replacing the browser driver."""
    browser._page_state = MethodType(_visible_page_state, browser)
    browser._requires_human = MethodType(_visibility_aware_requires_human, browser)
    vacancy_sync.LISTING_STATE_SCRIPT = SAFE_LISTING_STATE_SCRIPT
