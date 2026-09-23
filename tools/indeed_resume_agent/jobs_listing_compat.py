from __future__ import annotations

from . import vacancy_sync


JOBS_LISTING_STATE_SCRIPT = r"""
(() => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const lower = (v) => clean(v).toLowerCase();
  const identityAttrs = [
    'data-job-id', 'data-jobid', 'data-job-key', 'data-jobkey',
    'data-indeed-job-id', 'data-indeed-job-key'
  ];
  const ignoredExact = new Set([
    '', 'todos', 'nuevos', 'nuevo', 'all', 'new', 'abierto', 'pausado',
    'open', 'paused', 'patrocinar empleo', 'sponsor job', 'ver empleos',
    'view jobs', 'publicar un empleo', 'post a job', 'mensajes', 'messages'
  ]);
  const ignoredContains = [
    'más opciones', 'mas opciones', 'more options', 'acciones', 'actions',
    'seleccionar', 'select job', 'ayuda', 'help', 'notificaciones', 'notifications'
  ];

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

  const jobKeyFromHref = (rawHref) => {
    const href = clean(rawHref);
    if (!href) return '';
    try {
      const url = new URL(href, location.href);
      if (url.protocol !== 'https:' || url.hostname !== 'employers.indeed.com') return '';
      for (const key of ['jobId', 'jobid', 'jk', 'jobKey', 'jobkey']) {
        const value = clean(url.searchParams.get(key));
        if (value && /^[A-Za-z0-9_-]{3,200}$/.test(value)) return value;
      }
      const match = String(url.pathname || '').match(/\/(?:jobs?|job)\/(?:view\/)?([A-Za-z0-9_-]{3,200})(?:\/|$)/i);
      if (match && !['view', 'open', 'paused', 'create', 'new'].includes(match[1].toLowerCase())) {
        return match[1];
      }
    } catch (_) {}
    return '';
  };

  const jobKeyFromElement = (root) => {
    if (!root) return '';
    const nodes = [root, ...Array.from(root.querySelectorAll?.('*') || [])];
    for (const node of nodes) {
      const hrefKey = jobKeyFromHref(node.href || node.getAttribute?.('href') || '');
      if (hrefKey) return hrefKey;
      for (const attr of identityAttrs) {
        const value = clean(node.getAttribute?.(attr));
        if (value && /^[A-Za-z0-9_-]{3,200}$/.test(value)) return value;
      }
    }
    return '';
  };

  const labelOf = (node) => clean(
    node?.getAttribute?.('aria-label') || node?.innerText || node?.textContent || ''
  );

  const isIgnoredClickable = (node) => {
    const label = lower(labelOf(node));
    if (!label || ignoredExact.has(label)) return true;
    return ignoredContains.some((part) => label.includes(part));
  };

  const hasStatus = (text) => /(abierto|pausado|open|paused)/i.test(String(text || ''));
  const hasJobSemanticHint = (node) => {
    const attrs = lower([
      node?.getAttribute?.('class'), node?.getAttribute?.('id'),
      node?.getAttribute?.('data-testid'), node?.getAttribute?.('aria-label'),
      node?.getAttribute?.('role')
    ].filter(Boolean).join(' '));
    return /(job|empleo|vacan)/i.test(attrs);
  };
  const looksLikeHeaderOrPage = (text) => {
    const value = lower(text);
    const hasTitleHeader = value.includes('título del empleo') || value.includes('titulo del empleo') || value.includes('job title');
    const hasStatusHeader = value.includes('estado del empleo') || value.includes('job status');
    return hasTitleHeader && hasStatusHeader;
  };

  const findRowRoot = (clickable) => {
    let node = clickable?.parentElement || null;
    for (let depth = 0; node && depth < 10; depth += 1, node = node.parentElement) {
      if (!isVisible(node)) continue;
      if (node === document.body || node === document.documentElement) break;
      const text = clean(node.innerText || node.textContent || '');
      if (!text || text.length > 1800 || looksLikeHeaderOrPage(text)) continue;
      const key = jobKeyFromElement(node);
      const status = hasStatus(text);
      const semantic = hasJobSemanticHint(node);
      const multiCell = (node.children?.length || 0) >= 2;
      if (key || (status && (semantic || multiCell))) return node;
    }
    return null;
  };

  const clickables = Array.from(document.querySelectorAll(
    '[data-testid*="title" i], button[role="link"], [role="link"], a[href], button'
  )).filter((node) => isVisible(node) && !isIgnoredClickable(node));

  const roots = [];
  const rootToClickable = new Map();
  for (const clickable of clickables) {
    const href = clean(clickable.href || clickable.getAttribute?.('href') || '');
    if (href) {
      try {
        const url = new URL(href, location.href);
        if (url.hostname !== 'employers.indeed.com') continue;
      } catch (_) {
        continue;
      }
    }
    const root = findRowRoot(clickable);
    if (!root) continue;
    if (!rootToClickable.has(root)) {
      rootToClickable.set(root, clickable);
      roots.push(root);
    }
  }

  const listingUrl = document.baseURI || location.href;
  const rowScrollY = window.scrollY;
  const rows = [];
  const seen = new Set();
  let clickIndex = 0;

  for (const [rootIndex, root] of roots.slice(0, 1000).entries()) {
    const clickable = rootToClickable.get(root);
    if (!clickable) continue;
    const title = labelOf(clickable);
    const rowText = clean(root.innerText || root.textContent || '');
    if (!title || !rowText) continue;

    const href = clean(clickable.href || clickable.getAttribute?.('href') || '');
    const externalJobKey = jobKeyFromHref(href) || jobKeyFromElement(root);
    if (!externalJobKey && !hasStatus(rowText)) continue;

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

  let nextHref = '';
  for (const selector of [
    'a[rel="next"]', 'a[aria-label*="next" i]',
    'a[aria-label*="siguiente" i]', 'a[data-testid*="pagination" i]'
  ]) {
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

  const scrollRoot = document.scrollingElement || document.documentElement;
  const previousScrollY = window.scrollY;
  const viewportHeight = Math.max(1, window.innerHeight || 1);
  const scrollHeight = Math.max(
    scrollRoot?.scrollHeight || 0,
    document.body?.scrollHeight || 0
  );
  if (scrollHeight > previousScrollY + viewportHeight + 4) {
    window.scrollBy(0, Math.max(480, Math.floor(viewportHeight * 0.8)));
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


def install_jobs_listing_compat() -> None:
    vacancy_sync.LISTING_STATE_SCRIPT = JOBS_LISTING_STATE_SCRIPT
