from __future__ import annotations

import asyncio

from . import vacancy_sync
from .indeed_jobs_current import _advance_page, _listing_state


async def _scroll_listing(browser, cdp) -> bool:
    """Advance the current Indeed listing without assuming button pagination.

    Indeed can virtualize the job table or lazy-load additional rows while the
    outer document itself barely moves. Prefer the largest visible scrollable
    container, then fall back to the document viewport.
    """

    value = await browser._evaluate(
        cdp,
        r"""
(() => {
  const visible = (node) => {
    if (!node) return false;
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.display !== 'none'
      && style.visibility !== 'hidden'
      && rect.width > 0
      && rect.height > 0;
  };
  const candidates = Array.from(document.querySelectorAll('main,section,div,tbody'))
    .filter((node) => {
      if (!visible(node)) return false;
      const style = getComputedStyle(node);
      const overflowY = String(style.overflowY || '').toLowerCase();
      const scrollable = overflowY === 'auto' || overflowY === 'scroll';
      return scrollable && Number(node.scrollHeight || 0) > Number(node.clientHeight || 0) + 80;
    })
    .sort((a, b) => Number(b.scrollHeight || 0) - Number(a.scrollHeight || 0));

  for (const node of candidates) {
    const before = Number(node.scrollTop || 0);
    const step = Math.max(420, Math.floor(Number(node.clientHeight || 600) * 0.82));
    node.scrollTop = Math.min(
      Number(node.scrollHeight || 0),
      before + step
    );
    if (Number(node.scrollTop || 0) > before) return true;
  }

  const scrolling = document.scrollingElement || document.documentElement || document.body;
  const before = Number(window.scrollY || scrolling?.scrollTop || 0);
  const maxTop = Math.max(
    0,
    Number(scrolling?.scrollHeight || 0) - Math.max(1, Number(window.innerHeight || 1))
  );
  if (before >= maxTop) return false;
  const step = Math.max(420, Math.floor(Math.max(1, Number(window.innerHeight || 1)) * 0.82));
  window.scrollTo(0, Math.min(maxTop, before + step));
  return Number(window.scrollY || scrolling?.scrollTop || 0) > before;
})()
""",
    )
    if not value:
        return False
    await asyncio.sleep(0.3)
    return True


def _harvest_rows(state: dict, discovered: dict[str, dict]) -> tuple[int, bool]:
    """Copy stable listing rows into the run-level map.

    Returns (invalid_rows, added_any). Stable provider identity remains required;
    title-only rows are never promoted into backend snapshots.
    """

    invalid_rows = 0
    before = len(discovered)
    for row in list(state.get("rows") or []):
        if not isinstance(row, dict):
            invalid_rows += 1
            continue
        key = str(row.get("externalJobKey") or "").strip().lower()
        href = vacancy_sync._safe_job_url(row.get("href"))
        title = " ".join(str(row.get("title") or "").split()).strip()
        if not key or not href or not title:
            invalid_rows += 1
            continue
        normalized = dict(row)
        normalized["externalJobKey"] = key[:200]
        normalized["href"] = href
        normalized["title"] = title
        discovered[key[:200]] = normalized
    return invalid_rows, len(discovered) > before


async def _discover_jobs(browser, cdp) -> tuple[dict[str, dict], dict]:
    await browser._navigate(cdp, vacancy_sync.INDEED_JOBS_URL)
    if await browser._requires_human(cdp):
        raise RuntimeError("INDEED_AUTH_REQUIRED")

    discovered: dict[str, dict] = {}
    expected_total = 0
    list_incomplete = False
    invalid_rows = 0
    pages = 0
    scroll_rounds = 0
    visited_next_urls: set[str] = {vacancy_sync.INDEED_JOBS_URL}

    for page_index in range(50):
        pages = page_index + 1
        deadline = asyncio.get_running_loop().time() + max(
            12.0,
            float(browser._config.request_timeout_seconds),
        )
        state: dict = {}
        while asyncio.get_running_loop().time() < deadline:
            state = await _listing_state(browser, cdp)
            expected_total = max(expected_total, int(state.get("expectedTotal") or 0))
            if state.get("rows"):
                break
            await asyncio.sleep(0.25)

        if not state.get("rows"):
            if not discovered:
                raise RuntimeError("INDEED_JOB_LIST_NOT_READY")
            list_incomplete = True
            break

        invalid, _ = _harvest_rows(state, discovered)
        invalid_rows += invalid
        if invalid:
            list_incomplete = True

        # Current Indeed sometimes renders only the first virtualized chunk and
        # exposes neither a Next button nor an anchor. Exhaust lazy scrolling on
        # the current listing before concluding that the page is complete.
        stagnant_scrolls = 0
        for _ in range(50):
            if expected_total and len(discovered) >= expected_total:
                break
            try:
                moved = await _scroll_listing(browser, cdp)
            except RuntimeError as exc:
                if str(exc) == "INDEED_AUTH_REQUIRED":
                    raise
                moved = False
            except Exception:
                moved = False
            if not moved:
                break

            scroll_rounds += 1
            if await browser._requires_human(cdp):
                raise RuntimeError("INDEED_AUTH_REQUIRED")
            next_state = await _listing_state(browser, cdp)
            expected_total = max(expected_total, int(next_state.get("expectedTotal") or 0))
            invalid, added = _harvest_rows(next_state, discovered)
            invalid_rows += invalid
            if invalid:
                list_incomplete = True
            state = next_state
            if added:
                stagnant_scrolls = 0
            else:
                stagnant_scrolls += 1
                # One inert movement can be a render delay; two means we have
                # exhausted this scroll surface and should try pagination.
                if stagnant_scrolls >= 2:
                    break

        if expected_total and len(discovered) >= expected_total:
            break

        # Some Indeed layouts expose a concrete pagination URL but no enabled
        # Next button. Follow that URL before relying on button automation.
        next_href = vacancy_sync._safe_job_url(state.get("nextHref"))
        if next_href:
            if next_href in visited_next_urls:
                list_incomplete = True
                break
            if page_index >= 49:
                list_incomplete = True
                break
            visited_next_urls.add(next_href)
            await browser._navigate(cdp, next_href)
            if await browser._requires_human(cdp):
                raise RuntimeError("INDEED_AUTH_REQUIRED")
            continue

        if state.get("hasNextPage"):
            if page_index >= 49:
                list_incomplete = True
                break
            signature = str(state.get("pageSignature") or "")
            if not signature:
                list_incomplete = True
                break
            try:
                advanced = await _advance_page(browser, cdp, signature)
            except RuntimeError as exc:
                if str(exc) == "INDEED_AUTH_REQUIRED":
                    raise
                advanced = False
            if not advanced:
                list_incomplete = True
                break
            continue

        # There is no remaining progression strategy on this page.
        break

    if not discovered:
        raise RuntimeError("INDEED_JOB_LIST_NOT_READY")
    if expected_total and len(discovered) < expected_total:
        list_incomplete = True

    diagnostics = {
        "expected_total": expected_total,
        "discovered": len(discovered),
        "pages": pages,
        "scroll_rounds": scroll_rounds,
        "invalid_rows": invalid_rows,
        "list_incomplete": list_incomplete,
    }
    return discovered, diagnostics


async def _wait_for_job_description(browser, cdp, expected_title: str) -> dict:
    """Wait for the current job detail to hydrate its actual description.

    The generic historical helper may return as soon as the title appears. For
    vacancy synchronization the description is required, so title-only hydration
    is deliberately not considered ready.
    """

    normalized_expected = vacancy_sync._normalized_discovery_text(expected_title)
    last_state: dict = {}
    deadline = asyncio.get_running_loop().time() + max(
        12.0,
        float(browser._config.request_timeout_seconds),
    )
    while asyncio.get_running_loop().time() < deadline:
        if await browser._requires_human(cdp):
            raise RuntimeError("INDEED_AUTH_REQUIRED")
        last_state = await vacancy_sync._detail_state(browser, cdp)
        if not last_state.get("loading"):
            description = str(last_state.get("description") or "").strip()
            detail_title = vacancy_sync._normalized_discovery_text(last_state.get("title"))
            title_matches = not detail_title or not normalized_expected or normalized_expected in detail_title
            if description and title_matches:
                return last_state
        await asyncio.sleep(0.2)
    return last_state


async def _hydrate_jobs(browser, cdp, discovered: dict[str, dict]) -> tuple[list[dict], dict]:
    snapshots: list[dict] = []
    detail_failures = 0
    descriptions_extracted = 0

    for key, row in discovered.items():
        href = vacancy_sync._safe_job_url(row.get("href"))
        if not href:
            detail_failures += 1
            continue

        try:
            await browser._navigate(cdp, href)
            if await browser._requires_human(cdp):
                raise RuntimeError("INDEED_AUTH_REQUIRED")
            detail = await _wait_for_job_description(browser, cdp, row["title"])
        except RuntimeError as exc:
            if str(exc) == "INDEED_AUTH_REQUIRED":
                raise
            detail_failures += 1
            continue
        except Exception:
            detail_failures += 1
            continue

        detail_title = " ".join(str(detail.get("title") or row["title"]).split()).strip()
        description = str(detail.get("description") or "").strip()
        if not detail_title or not description:
            detail_failures += 1
            continue

        descriptions_extracted += 1
        snapshots.append(
            {
                "external_job_key": key,
                "title": detail_title,
                "description": description,
                "status": str(detail.get("status") or row.get("status") or "").strip() or None,
                "location": str(detail.get("location") or row.get("location") or "").strip() or None,
                "posted_at": str(detail.get("postedAt") or row.get("postedAt") or "").strip() or None,
            }
        )

    return snapshots, {
        "hydrated": len(snapshots),
        "detail_failures": detail_failures,
        "descriptions_extracted": descriptions_extracted,
    }


async def _collect_resilient_jobs(browser) -> list[dict]:
    cdp = await browser._ensure_started()
    discovered, diagnostics = await _discover_jobs(browser, cdp)
    snapshots, detail_diagnostics = await _hydrate_jobs(browser, cdp, discovered)
    diagnostics.update(detail_diagnostics)
    browser._last_job_sync_diagnostics = diagnostics

    if not snapshots:
        raise RuntimeError("INDEED_JOB_DETAILS_EMPTY")
    return snapshots


def install_resilient_vacancy_pipeline() -> None:
    """Use a partial-safe two-phase vacancy crawler.

    Discovery completeness is diagnostic, not destructive: stable vacancies that
    were successfully discovered and hydrated are synchronized even when Indeed's
    result counter and traversed rows disagree. Authentication remains a hard
    blocker and a run with zero usable descriptions still fails closed.
    """

    vacancy_sync._collect_async = _collect_resilient_jobs
