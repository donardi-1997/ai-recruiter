from __future__ import annotations

import asyncio

from . import vacancy_sync
from .indeed_jobs_current import _advance_page, _listing_state


async def _discover_jobs(browser, cdp) -> tuple[dict[str, dict], dict]:
    await browser._navigate(cdp, vacancy_sync.INDEED_JOBS_URL)
    if await browser._requires_human(cdp):
        raise RuntimeError("INDEED_AUTH_REQUIRED")

    discovered: dict[str, dict] = {}
    expected_total = 0
    list_incomplete = False
    invalid_rows = 0
    pages = 0

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

        rows = list(state.get("rows") or [])
        if not rows:
            if not discovered:
                raise RuntimeError("INDEED_JOB_LIST_NOT_READY")
            list_incomplete = True
            break

        for row in rows:
            if not isinstance(row, dict):
                invalid_rows += 1
                list_incomplete = True
                continue
            key = str(row.get("externalJobKey") or "").strip().lower()
            href = vacancy_sync._safe_job_url(row.get("href"))
            title = " ".join(str(row.get("title") or "").split()).strip()
            if not key or not href or not title:
                invalid_rows += 1
                list_incomplete = True
                continue
            normalized = dict(row)
            normalized["externalJobKey"] = key[:200]
            normalized["href"] = href
            normalized["title"] = title
            discovered[key[:200]] = normalized

        if not state.get("hasNextPage"):
            break

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

    if not discovered:
        raise RuntimeError("INDEED_JOB_LIST_NOT_READY")
    if expected_total and len(discovered) < expected_total:
        list_incomplete = True

    diagnostics = {
        "expected_total": expected_total,
        "discovered": len(discovered),
        "pages": pages,
        "invalid_rows": invalid_rows,
        "list_incomplete": list_incomplete,
    }
    return discovered, diagnostics


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
            detail = await vacancy_sync._wait_for_detail(browser, cdp, row["title"])
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
