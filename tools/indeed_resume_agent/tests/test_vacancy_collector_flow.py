from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tools.indeed_resume_agent import vacancy_sync


class FakeVacancyBrowser:
    def __init__(self):
        self._config = SimpleNamespace(request_timeout_seconds=1)
        self.current_detail = None
        self.navigations = []
        self.clicks = []
        self.listing_calls = 0

    async def _ensure_started(self):
        return object()

    async def _navigate(self, cdp, url):
        self.navigations.append(url)

    async def _requires_human(self, cdp):
        return False

    async def _evaluate(self, cdp, script):
        if script == vacancy_sync.LISTING_STATE_SCRIPT:
            self.listing_calls += 1
            return {
                "rows": [
                    {
                        "externalJobKey": "",
                        "title": "ASESOR COMERCIAL",
                        "href": "",
                        "rowText": "ASESOR COMERCIAL 0 Todos 0 Nuevos Bogotá Abierto",
                        "clickToken": "row-one",
                        "listingUrl": vacancy_sync.INDEED_JOBS_URL,
                        "scrollY": 0,
                    },
                    {
                        "externalJobKey": "",
                        "title": "ASESOR COMERCIAL",
                        "href": "",
                        "rowText": "ASESOR COMERCIAL 0 Todos 0 Nuevos Bogotá Abierto",
                        "clickToken": "row-two",
                        "listingUrl": vacancy_sync.INDEED_JOBS_URL,
                        "scrollY": 0,
                    },
                ],
                "nextHref": "",
                "scrollY": 100,
                "viewportHeight": 600,
                "scrollHeight": 700,
            }

        if script == vacancy_sync.DETAIL_STATE_SCRIPT:
            assert self.current_detail is not None
            return self.current_detail

        if "window.scrollTo" in script:
            return True

        if "const target =" in script and "data-asiati-vacancy-token" in script:
            if "row-one" in script:
                self.clicks.append("row-one")
                self.current_detail = {
                    "url": vacancy_sync.INDEED_JOBS_URL,
                    "externalJobKey": "indeed-job-one",
                    "title": "ASESOR COMERCIAL",
                    "description": "Primera publicación comercial con responsabilidades completas y trazables.",
                    "location": "Bogotá",
                    "status": "Abierto",
                    "postedAt": "2026-09-20T12:00:00Z",
                    "loading": False,
                }
                return True
            if "row-two" in script:
                self.clicks.append("row-two")
                self.current_detail = {
                    "url": vacancy_sync.INDEED_JOBS_URL,
                    "externalJobKey": "indeed-job-two",
                    "title": "ASESOR COMERCIAL",
                    "description": "Segunda publicación comercial con un alcance distinto y descripción completa.",
                    "location": "Bogotá",
                    "status": "Abierto",
                    "postedAt": "2026-09-21T12:00:00Z",
                    "loading": False,
                }
                return True
            return False

        if "button[aria-label*=" in script and "close" in script:
            return True

        raise AssertionError(f"unexpected browser script: {script[:100]!r}")


def test_collector_opens_each_identical_row_and_keeps_distinct_detail_identities():
    browser = FakeVacancyBrowser()

    snapshots = asyncio.run(vacancy_sync._collect_async(browser))

    assert browser.clicks == ["row-one", "row-two"]
    assert {snapshot["external_job_key"] for snapshot in snapshots} == {
        "indeed-job-one",
        "indeed-job-two",
    }
    assert {snapshot["description"] for snapshot in snapshots} == {
        "Primera publicación comercial con responsabilidades completas y trazables.",
        "Segunda publicación comercial con un alcance distinto y descripción completa.",
    }
