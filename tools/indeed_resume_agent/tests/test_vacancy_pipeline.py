from __future__ import annotations

import asyncio

from tools.indeed_resume_agent import vacancy_pipeline


class Config:
    request_timeout_seconds = 1


class Browser:
    _config = Config()

    def __init__(self):
        self.navigations = []
        self._last_job_sync_diagnostics = None

    async def _ensure_started(self):
        return object()

    async def _navigate(self, _cdp, url):
        self.navigations.append(url)

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


def test_discovery_keeps_stable_rows_when_indeed_counter_is_higher(monkeypatch):
    browser = Browser()

    async def listing_state(_browser, _cdp):
        return {
            "rows": [_row("job-1", "Vacante uno"), _row("job-2", "Vacante dos")],
            "expectedTotal": 407,
            "hasNextPage": False,
            "pageSignature": "job-1|job-2",
        }

    monkeypatch.setattr(vacancy_pipeline, "_listing_state", listing_state)

    discovered, diagnostics = asyncio.run(vacancy_pipeline._discover_jobs(browser, object()))

    assert list(discovered) == ["job-1", "job-2"]
    assert diagnostics["expected_total"] == 407
    assert diagnostics["discovered"] == 2
    assert diagnostics["list_incomplete"] is True


def test_wait_for_job_description_does_not_accept_title_only_hydration(monkeypatch):
    browser = Browser()
    states = iter(
        [
            {"title": "Vacante uno", "description": "", "loading": False},
            {
                "title": "Vacante uno",
                "description": "Descripción completa que llegó después del título.",
                "loading": False,
            },
        ]
    )
    calls = 0

    async def detail_state(_browser, _cdp):
        nonlocal calls
        calls += 1
        return next(states)

    monkeypatch.setattr(vacancy_pipeline.vacancy_sync, "_detail_state", detail_state)

    detail = asyncio.run(
        vacancy_pipeline._wait_for_job_description(browser, object(), "Vacante uno")
    )

    assert calls == 2
    assert detail["description"].startswith("Descripción completa")


def test_hydration_enters_every_discovered_vacancy_and_requires_description(monkeypatch):
    browser = Browser()
    discovered = {
        "job-1": _row("job-1", "Vacante uno"),
        "job-2": _row("job-2", "Vacante dos"),
        "job-3": _row("job-3", "Vacante tres"),
    }

    async def wait_for_description(_browser, _cdp, expected_title):
        if expected_title == "Vacante dos":
            return {"title": expected_title, "description": ""}
        return {
            "title": expected_title,
            "description": f"Descripción completa para {expected_title}",
            "status": "Abierto",
            "location": "Bogotá",
        }

    monkeypatch.setattr(
        vacancy_pipeline,
        "_wait_for_job_description",
        wait_for_description,
    )

    snapshots, diagnostics = asyncio.run(
        vacancy_pipeline._hydrate_jobs(browser, object(), discovered)
    )

    detail_urls = [url for url in browser.navigations if "/jobs/view" in url]
    assert len(detail_urls) == 3
    assert [row["external_job_key"] for row in snapshots] == ["job-1", "job-3"]
    assert all(row["description"] for row in snapshots)
    assert diagnostics["hydrated"] == 2
    assert diagnostics["descriptions_extracted"] == 2
    assert diagnostics["detail_failures"] == 1


def test_auth_during_vacancy_detail_is_a_hard_blocker(monkeypatch):
    browser = Browser()
    calls = 0

    async def requires_human(_cdp):
        nonlocal calls
        calls += 1
        return calls >= 1

    browser._requires_human = requires_human

    try:
        asyncio.run(
            vacancy_pipeline._hydrate_jobs(
                browser,
                object(),
                {"job-1": _row("job-1", "Vacante uno")},
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "INDEED_AUTH_REQUIRED"
    else:
        raise AssertionError("Expected INDEED_AUTH_REQUIRED")
