from __future__ import annotations

import asyncio
import json
import time
from types import MethodType
from urllib.parse import parse_qs, urljoin, urlsplit

from .browser_use_driver import (
    _candidate_recency_key,
    _candidate_search_queries,
    _candidate_search_url,
    _normalize_lookup_text,
)


CURRENT_CANDIDATE_LIST_SCRIPT = r"""
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
  const candidateIdFromHref = (rawHref) => {
    const href = clean(rawHref);
    if (!href) return '';
    try {
      const url = new URL(href, location.href);
      if (url.protocol !== 'https:' || url.hostname !== 'employers.indeed.com') return '';
      if (url.pathname !== '/candidates/view') return '';
      const value = clean(url.searchParams.get('id'));
      return /^[A-Za-z0-9_-]{3,200}$/.test(value) ? value : '';
    } catch (_) {
      return '';
    }
  };
  const stripJobPrefix = (value) => clean(value)
    .replace(/^(?:Empleo al que se postuló|Job applied to)\s*:\s*/i, '');

  const rows = [];
  const seen = new Set();
  const links = Array.from(document.querySelectorAll(
    'a[data-testid="NameCell"][href*="/candidates/view"]'
  ));
  for (const [index, link] of links.entries()) {
    if (!visible(link)) continue;
    const href = String(link.href || link.getAttribute('href') || '');
    const candidateId = candidateIdFromHref(href);
    const name = clean(link.innerText || link.textContent || '');
    if (!candidateId || !name || seen.has(candidateId)) continue;
    const row = link.closest('tr[role="row"], tr');
    if (!row || !visible(row)) continue;
    seen.add(candidateId);

    const jobNode = row.querySelector('[data-testid="CandidateInfoColumn-job-applied-to"]');
    const statusNode = row.querySelector('[data-testid="CandidateInfoColumn-status"]');
    const appliedNode = row.querySelector('[data-testid="CandidateInfoColumn-apply"]');
    const activityNode = row.querySelector('[data-testid="stackable-guided-nudge"]');
    const locationNode = row.querySelector('[data-testid="CandidateInfoColumn-location"]');
    const appliedAt = clean(
      row.querySelector('time[datetime]')?.getAttribute('datetime')
      || row.getAttribute('data-applied-at')
      || row.getAttribute('data-application-date')
      || ''
    );
    rows.push({
      candidateId,
      name,
      jobTitle: stripJobPrefix(jobNode?.innerText || jobNode?.textContent || ''),
      status: clean(statusNode?.innerText || statusNode?.textContent || ''),
      appliedLabel: clean(appliedNode?.innerText || appliedNode?.textContent || ''),
      activity: clean(activityNode?.innerText || activityNode?.textContent || ''),
      location: clean(locationNode?.innerText || locationNode?.textContent || ''),
      rowText: clean(row.innerText || row.textContent || ''),
      href,
      index,
      appliedAt,
    });
  }

  const body = clean(document.body?.innerText || '');
  let expectedTotal = 0;
  const totalMatch = body.match(/(?:Mostrando|Showing)\s+\d+\s+(?:a|to)\s+\d+\s+(?:de|of)\s+([0-9.,]+)/i);
  if (totalMatch) expectedTotal = Number(String(totalMatch[1]).replace(/[^0-9]/g, '')) || 0;

  const buttons = Array.from(document.querySelectorAll('button'));
  const nextButton = buttons.find((button) => {
    const label = clean(button.getAttribute('aria-label') || button.innerText || button.textContent || '').toLowerCase();
    return label === 'siguiente' || label === 'next';
  }) || null;
  const hasNextPage = Boolean(
    nextButton
    && visible(nextButton)
    && !nextButton.disabled
    && String(nextButton.getAttribute('aria-disabled') || '').toLowerCase() !== 'true'
  );

  return {
    url: String(location.href || ''),
    rows,
    expectedTotal,
    hasNextPage,
    pageSignature: rows.map((row) => row.candidateId).join('|'),
  };
})()
"""


CURRENT_CANDIDATE_DETAIL_SCRIPT = r"""
(() => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  let candidateId = '';
  try {
    const url = new URL(location.href);
    if (url.hostname === 'employers.indeed.com' && url.pathname === '/candidates/view') {
      const value = clean(url.searchParams.get('id'));
      if (/^[A-Za-z0-9_-]{3,200}$/.test(value)) candidateId = value;
    }
  } catch (_) {}

  const profile = document.querySelector('#candidateProfileContainer')
    || document.querySelector('[data-testid="namePlate"]')?.parentElement
    || document.body;
  const heading = clean(
    profile?.querySelector('[data-testid="name-plate-name-item"] h1, [data-testid="name-plate-name-item"] h2')?.innerText
    || profile?.querySelector('h1, h2')?.innerText
    || ''
  );
  const jobLink = profile?.querySelector('a[href*="/jobs/view?employerJobId="]') || null;
  const jobTitle = clean(jobLink?.innerText || jobLink?.textContent || '')
    .split(/\s*[•·]\s*/, 1)[0]
    .trim();

  const controls = Array.from(profile?.querySelectorAll('button, a, [role="button"]') || []);
  const downloadReady = controls.some((el) => {
    const testId = clean(el.getAttribute('data-testid')).toLowerCase();
    if (testId === 'download-resume-inline' || testId === 'download-resume-moreactions') {
      return true;
    }
    const label = clean(el.getAttribute('aria-label') || el.innerText || el.getAttribute('title') || '').toLowerCase();
    return [
      'descargar cv', 'descargar hv', 'descargar resume', 'descargar currículum', 'descargar curriculum',
      'descargar hoja de vida', 'download cv', 'download hv', 'download resume', 'view cv', 'view resume',
      'ver cv', 'ver hv', 'ver currículum', 'ver curriculum', 'ver hoja de vida'
    ].includes(label);
  });
  const body = clean(profile?.innerText || profile?.textContent || '');
  return {
    url: String(location.href || ''),
    candidateId,
    heading,
    jobTitle,
    body: body.slice(0, 12000),
    downloadReady,
  };
})()
"""


def candidate_id_from_url(raw_url: str | None) -> str:
    value = str(raw_url or '').strip()
    if not value:
        return ''
    try:
        parsed = urlsplit(value)
    except Exception:
        return ''
    if parsed.scheme.casefold() != 'https' or str(parsed.hostname or '').casefold() != 'employers.indeed.com':
        return ''
    if str(parsed.path or '') != '/candidates/view':
        return ''
    candidate_id = str((parse_qs(parsed.query).get('id') or [''])[0]).strip()
    if not candidate_id or len(candidate_id) > 200:
        return ''
    return candidate_id if all(ch.isalnum() or ch in '_-' for ch in candidate_id) else ''


def select_current_candidate(
    rows: list[dict],
    candidate_name: str,
    job_title: str | None,
) -> tuple[dict | None, str | None]:
    target_name = _normalize_lookup_text(candidate_name)
    target_job = _normalize_lookup_text(job_title)
    exact = [
        row for row in rows
        if _normalize_lookup_text(row.get('name')) == target_name
    ]
    if not exact:
        return None, None
    if target_job:
        job_matches = [
            row for row in exact
            if _normalize_lookup_text(row.get('jobTitle')) == target_job
        ]
        if not job_matches:
            return None, None
        return max(job_matches, key=_candidate_recency_key), None
    return max(exact, key=_candidate_recency_key), None


async def _candidate_listing_state(browser, cdp) -> dict:
    value = await browser._evaluate(cdp, CURRENT_CANDIDATE_LIST_SCRIPT)
    return value if isinstance(value, dict) else {
        'rows': [], 'expectedTotal': 0, 'hasNextPage': False, 'pageSignature': ''
    }


async def _candidate_rows_current(self, cdp) -> list[dict]:
    return list((await _candidate_listing_state(self, cdp)).get('rows') or [])


def _select_candidate_current(
    self,
    rows: list[dict],
    candidate_name: str,
    job_title: str | None,
) -> tuple[dict | None, str | None]:
    return select_current_candidate(rows, candidate_name, job_title)


async def _advance_candidate_page(browser, cdp, previous_signature: str) -> bool:
    clicked = bool(await browser._evaluate(cdp, r"""
(() => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const button = Array.from(document.querySelectorAll('button')).find((el) => {
    const label = clean(el.getAttribute('aria-label') || el.innerText || el.textContent || '');
    return label === 'siguiente' || label === 'next';
  });
  if (!button || button.disabled || String(button.getAttribute('aria-disabled') || '').toLowerCase() === 'true') {
    return false;
  }
  button.click();
  return true;
})()
"""))
    if not clicked:
        return False
    deadline = time.monotonic() + max(8.0, float(browser._config.request_timeout_seconds))
    while time.monotonic() < deadline:
        await asyncio.sleep(0.2)
        if await browser._requires_human(cdp):
            raise RuntimeError('INDEED_AUTH_REQUIRED')
        state = await _candidate_listing_state(browser, cdp)
        signature = str(state.get('pageSignature') or '')
        if signature and signature != previous_signature and state.get('rows'):
            return True
    return False


async def _open_selected_candidate(browser, cdp, target: dict) -> str | None:
    href = str(target.get('href') or '').strip()
    expected_id = str(target.get('candidateId') or '').strip()
    expected_name = _normalize_lookup_text(target.get('name'))
    expected_job = _normalize_lookup_text(target.get('jobTitle'))
    if not href or not expected_id or not expected_name:
        return 'INDEED_CANDIDATE_OPEN_FAILED'
    if candidate_id_from_url(href) != expected_id:
        return 'INDEED_CANDIDATE_OPEN_FAILED'

    await browser._navigate(cdp, urljoin('https://employers.indeed.com/', href))
    deadline = time.monotonic() + max(8.0, float(browser._config.request_timeout_seconds))
    while time.monotonic() < deadline:
        if await browser._requires_human(cdp):
            return 'INDEED_AUTH_REQUIRED'
        detail = await browser._evaluate(cdp, CURRENT_CANDIDATE_DETAIL_SCRIPT)
        if isinstance(detail, dict):
            detail_id = str(detail.get('candidateId') or '').strip()
            detail_name = _normalize_lookup_text(detail.get('heading'))
            detail_job = _normalize_lookup_text(detail.get('jobTitle'))
            if not detail_job:
                detail_job = _normalize_lookup_text(detail.get('body'))
            id_matches = detail_id == expected_id
            name_matches = detail_name == expected_name
            job_matches = not expected_job or (
                detail_job == expected_job
                or expected_job in detail_job
            )
            if id_matches and name_matches and job_matches:
                return None
        await asyncio.sleep(0.2)
    return 'INDEED_CANDIDATE_OPEN_FAILED'


async def _scan_candidate_search(browser, cdp, name: str, job_title: str | None) -> str | None:
    for _page_index in range(50):
        deadline = time.monotonic() + 5.0
        state: dict = {}
        while time.monotonic() < deadline:
            state = await _candidate_listing_state(browser, cdp)
            rows = list(state.get('rows') or [])
            target, error = select_current_candidate(rows, name, job_title)
            if error:
                return error
            if target:
                return await _open_selected_candidate(browser, cdp, target)
            if rows:
                break
            await asyncio.sleep(0.25)

        if not state.get('hasNextPage'):
            return 'INDEED_CANDIDATE_NOT_FOUND'
        signature = str(state.get('pageSignature') or '')
        if not signature or not await _advance_candidate_page(browser, cdp, signature):
            return 'INDEED_CANDIDATE_LIST_INCOMPLETE'
    return 'INDEED_CANDIDATE_LIST_INCOMPLETE'


async def _open_candidate_current(
    self,
    cdp,
    candidate_name: str,
    job_title: str | None,
) -> str | None:
    name = ' '.join(str(candidate_name or '').split()).strip()
    if not name:
        return 'INDEED_CANDIDATE_NAME_MISSING'

    for query in _candidate_search_queries(name):
        await self._navigate(cdp, _candidate_search_url(query))
        if await self._requires_human(cdp):
            return 'INDEED_AUTH_REQUIRED'
        result = await _scan_candidate_search(self, cdp, name, job_title)
        if result is None:
            return None
        if result != 'INDEED_CANDIDATE_NOT_FOUND':
            return result

        if await self._fill_candidate_search(cdp, query):
            await asyncio.sleep(0.75)
            result = await _scan_candidate_search(self, cdp, name, job_title)
            if result is None:
                return None
            if result != 'INDEED_CANDIDATE_NOT_FOUND':
                return result

    return 'INDEED_CANDIDATE_NOT_FOUND'


def install_current_indeed_candidates(browser) -> None:
    browser._candidate_rows = MethodType(_candidate_rows_current, browser)
    browser._select_candidate = MethodType(_select_candidate_current, browser)
    browser._open_candidate = MethodType(_open_candidate_current, browser)
