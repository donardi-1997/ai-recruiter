from __future__ import annotations

import asyncio

from tools.indeed_resume_agent import vacancy_pipeline
from tools.indeed_resume_agent.api_client import AgentApiError, QueueStats
from tools.indeed_resume_agent.ui_v3 import _safe_code, build_ui_state
from tools.indeed_resume_agent.worker import WorkerSnapshot


class Config:
    request_timeout_seconds = 1


class Browser:
    _config = Config()

    def __init__(self):
        self.current_url = ""
        self.navigations: list[str] = []
        self.scroll_round = 0

    async def _navigate(self, _cdp, url):
        self.current_url = str(url)
        self.navigations.append(self.current_url)

    async def _requires_human(self, _cdp):
        return False


def _row(key: str, title: str) -> dict:
    return {
        "externalJobKey": key,
        "href": f"https://employers.indeed.com/jobs/view?jobId={key}",
        "title": title,
        "status": "Abierto",
        "location": "Bogotá",
        "postedAt": "2026-09-23",
    }


def test_discovery_follows_next_href_when_indeed_does_not_expose_next_button(monkeypatch):
    browser = Browser()
    page_two = "https://employers.indeed.com/jobs?status=open%2Cpaused&start=68"

    async def listing_state(_browser, _cdp):
        if _browser.current_url == page_two:
            return {
                "rows": [_row("job-69", "Vacante página dos")],
                "expectedTotal": 407,
                "hasNextPage": False,
                "nextHref": None,
                "pageSignature": "job-69",
            }
        return {
            "rows": [_row("job-1", "Vacante página uno")],
            "expectedTotal": 407,
            "hasNextPage": False,
            "nextHref": page_two,
            "pageSignature": "job-1",
        }

    async def no_scroll(_browser, _cdp):
        return False

    monkeypatch.setattr(vacancy_pipeline, "_listing_state", listing_state)
    monkeypatch.setattr(vacancy_pipeline, "_scroll_listing", no_scroll, raising=False)

    discovered, diagnostics = asyncio.run(vacancy_pipeline._discover_jobs(browser, object()))

    assert list(discovered) == ["job-1", "job-69"]
    assert page_two in browser.navigations
    assert diagnostics["pages"] == 2


def test_discovery_collects_rows_revealed_by_lazy_scroll_without_next_button(monkeypatch):
    browser = Browser()

    async def listing_state(_browser, _cdp):
        rows = [_row("job-1", "Vacante uno")]
        if _browser.scroll_round >= 1:
            rows.append(_row("job-2", "Vacante dos"))
        if _browser.scroll_round >= 2:
            rows.append(_row("job-3", "Vacante tres"))
        return {
            "rows": rows,
            "expectedTotal": 3,
            "hasNextPage": False,
            "nextHref": None,
            "pageSignature": "|".join(row["externalJobKey"] for row in rows),
        }

    async def scroll_listing(_browser, _cdp):
        if _browser.scroll_round >= 2:
            return False
        _browser.scroll_round += 1
        return True

    monkeypatch.setattr(vacancy_pipeline, "_listing_state", listing_state)
    monkeypatch.setattr(vacancy_pipeline, "_scroll_listing", scroll_listing, raising=False)

    discovered, diagnostics = asyncio.run(vacancy_pipeline._discover_jobs(browser, object()))

    assert list(discovered) == ["job-1", "job-2", "job-3"]
    assert diagnostics["expected_total"] == 3
    assert diagnostics["list_incomplete"] is False


def test_candidate_sync_failure_surfaces_specific_safe_backend_code():
    snapshot = WorkerSnapshot(
        "SYNC_FAILED",
        None,
        0,
        "Candidatos detenidos: RESUME_SYNC_PAGE_LIMIT",
    )
    state = build_ui_state(snapshot, QueueStats(0, 0, 0, 0, 0, 0))

    assert state.status_label == "Candidatos detenidos: RESUME_SYNC_PAGE_LIMIT"


def test_safe_code_uses_agent_api_error_code_instead_of_hiding_it():
    error = AgentApiError(409, "RESUME_SYNC_PAGE_LIMIT")

    assert _safe_code(error, "INDEED_CANDIDATE_SYNC_FAILED") == "RESUME_SYNC_PAGE_LIMIT"


def test_safe_code_preserves_gmail_stage_code_from_backend():
    error = AgentApiError(502, "GMAIL_TOKEN_REFRESH_REJECTED")

    assert _safe_code(error, "INDEED_CANDIDATE_SYNC_FAILED") == "GMAIL_TOKEN_REFRESH_REJECTED"
