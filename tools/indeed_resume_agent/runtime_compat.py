from __future__ import annotations

from types import MethodType

from . import vacancy_sync
from .browser_use_driver import _CHALLENGE_MARKERS, _URL_CHALLENGE_MARKERS


SAFE_LISTING_STATE_SCRIPT = r"""
(() => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const lower = (v) => clean(v).toLowerCase();
  const ignoredLabels = new Set([
    '', 'todos', 'nuevos', 'nuevo', 'all', 'new', 'abierto', 'pausado', 'open', 'paused',
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
        if (
          tail
          && !['view', 'details', 'edit', 'jobs', 'create', 'new'].includes(tail.toLowerCase())
        ) return tail;
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

  const hasJobSemanticHint = (node) => {
    const attrs = clean([
      node?.getAttribute?.('class'),
      node?.getAttribute?.('id'),
      node?.getAttribute?.('data-testid'),
      node?.getAttribute?.('aria-label'),
      node?.getAttribute?.('role')
    ].filter(Boolean).join(' ')).toLowerCase();
    return /(job|empleo|vacan)/i.test(attrs);
  };

  const looksLikeJobContainer = (node) => {
    if (!node || !isVisible(node)) return false;
    const text = lower(node.innerText || node.textContent || '');
    // Indeed renders adjacent inline cells/spans without guaranteed whitespace,
    // e.g. "Bogotá, CundinamarcaAbierto". Do not rely on word boundaries for
    // status detection; the other structural signals keep navigation out.
    const hasStatus = /(abierto|pausado|open|paused)/i.test(text);
    const hasCandidateCounts = /\b(candidatos|todos|nuevos|nuevo|candidates|all|new)\b/i.test(text);
    const hasJobHint = hasJobSemanticHint(node);
    return hasStatus && (hasCandidateCounts || hasJobHint) && Boolean(chooseClickable(node));
  };

  const roots = [];
  const seenRoots = new Set();
  const addRoot = (node) => {
    if (!node || seenRoots.has(node) || !isVisible(node)) return;
    seenRoots.add(node);
    roots.push(node);
  };

  for (const selector of ['tr', '[role="row"]', '[data-testid*="job" i]']) {
    for (const node of document.querySelectorAll(selector)) addRoot(node);
  }
  for (const node of document.querySelectorAll('article, li')) {
    if (jobKeyFromElement(node) || looksLikeJobContainer(node)) addRoot(node);
  }

  const listingUrl = document.baseURI || location.href;
  const rowScrollY = window.scrollY;
  const rows = [];
  const seen = new Set();
  let clickIndex = 0;
  for (const [rootIndex, root] of roots.slice(0, 500).entries()) {
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
      const hasStatus = /(abierto|pausado|open|paused)/i.test(text);
      const hasCandidateCounts = /\b(candidatos|todos|nuevos|nuevo|candidates|all|new)\b/i.test(text);
      const hasJobHint = hasJobSemanticHint(root);
      if (!(hasStatus && (hasCandidateCounts || hasJobHint))) continue;
    }

    const absoluteY = Math.round((root.getBoundingClientRect?.().top || 0) + window.scrollY);
    const instanceKey = externalJobKey
      ? `job:${externalJobKey}`
      : `pending:${rootIndex}:${absoluteY}:${title}:${rowText}`;
    if (seen.has(instanceKey)) continue;
    seen.add(instanceKey);

    let token = clean(root.getAttribute?.('data-asiati-vacancy-instance-token'));
    if (!token) {
      token = `asiati-job-${rootIndex}-${absoluteY}-${clickIndex++}`;
      root.setAttribute?.('data-asiati-vacancy-instance-token', token);
    }
    clickable.setAttribute('data-asiati-vacancy-token', token);
    rows.push({
      externalJobKey,
      title,
      href,
      rowText,
      clickToken: token,
      rowPosition: absoluteY,
      rowIndex: rootIndex,
      listingUrl,
      scrollY: rowScrollY,
    });
  }

  const nextSelectors = [
    'a[rel="next"]',
    'a[aria-label*="Next" i]',
    'a[aria-label*="Siguiente" i]',
    'a[data-testid*="pagination" i]'
  ];
  let nextHref = '';
  for (const selector of nextSelectors) {
    for (const node of document.querySelectorAll(selector)) {
      const href = clean(node.href || node.getAttribute?.('href') || '');
      if (!href) continue;
      try {
        const url = new URL(href, location.href);
        if (url.protocol === 'https:' && url.hostname === 'employers.indeed.com') {
          nextHref = url.href;
          break;
        }
      } catch (_) {}
    }
    if (nextHref) break;
  }

  const root = document.scrollingElement || document.documentElement;
  const previousScrollY = window.scrollY;
  const viewportHeight = Math.max(1, window.innerHeight || 1);
  const scrollHeight = Math.max(root?.scrollHeight || 0, document.body?.scrollHeight || 0);
  if (scrollHeight > previousScrollY + viewportHeight + 4) {
    const step = Math.max(480, Math.floor(viewportHeight * 0.8));
    window.scrollBy(0, step);
  }

  return {
    url: location.href,
    body: clean(document.body?.innerText || '').slice(0, 12000),
    rows,
    nextHref,
    scrollY: window.scrollY,
    previousScrollY,
    viewportHeight,
    scrollHeight,
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

    explicit_login_markers = (
        "sign in",
        "log in",
        "iniciar sesión",
        "iniciar sesion",
    )
    if any(marker in body for marker in explicit_login_markers):
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

    on_candidates_workspace = url.startswith("https://employers.indeed.com/candidates")
    has_candidate_identity = "indeed" in title and (
        "candidato" in title or "candidate" in title
    )
    has_candidate_list_controls = (
        ("buscar candidatos" in body and "candidatos" in body)
        or ("search candidates" in body and "candidates" in body)
        or "todos los candidatos" in body
        or "all candidates" in body
    )
    has_candidate_detail_controls = (
        "descargar cv" in body
        or "download resume" in body
        or "hoja de vida" in body
        or "download cv" in body
    )
    if (
        on_candidates_workspace
        and has_candidate_identity
        and (has_candidate_list_controls or has_candidate_detail_controls)
    ):
        return False

    return any(marker in body for marker in _CHALLENGE_MARKERS)


def install_runtime_compat(browser) -> None:
    """Apply narrowly scoped Indeed UI compatibility without replacing the browser driver."""
    browser._page_state = MethodType(_visible_page_state, browser)
    browser._requires_human = MethodType(_visibility_aware_requires_human, browser)
    vacancy_sync.LISTING_STATE_SCRIPT = SAFE_LISTING_STATE_SCRIPT
