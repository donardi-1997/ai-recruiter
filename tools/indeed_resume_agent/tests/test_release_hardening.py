from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from tools.indeed_resume_agent import vacancy_sync
from tools.indeed_resume_agent.runtime_compat import SAFE_LISTING_STATE_SCRIPT
from tools.indeed_resume_agent.vacancy_click_recovery import (
    click_listing_row_with_recovery,
    install_vacancy_click_recovery,
)


class _PageBrowser:
    def __init__(self, page):
        self._page = page

    async def _evaluate(self, _cdp, script):
        return await self._page.evaluate(script)


def test_duplicate_rows_after_reload_are_not_guessed_from_geometry():
    async def scenario():
        original = """
        <main><ul>
          <li class="job-card">
            <button role="link" onclick="window.clicked='first'">ASESOR COMERCIAL</button>
            <span>0 Todos · 0 Nuevos</span><span>Bogotá</span><span>Abierto</span>
          </li>
          <li class="job-card">
            <button role="link" onclick="window.clicked='second'">ASESOR COMERCIAL</button>
            <span>0 Todos · 0 Nuevos</span><span>Bogotá</span><span>Abierto</span>
          </li>
        </ul></main>
        """
        reordered = """
        <main><ul>
          <li class="job-card">
            <button role="link" onclick="window.clicked='second'">ASESOR COMERCIAL</button>
            <span>0 Todos · 0 Nuevos</span><span>Bogotá</span><span>Abierto</span>
          </li>
          <li class="job-card">
            <button role="link" onclick="window.clicked='first'">ASESOR COMERCIAL</button>
            <span>0 Todos · 0 Nuevos</span><span>Bogotá</span><span>Abierto</span>
          </li>
        </ul></main>
        """
        async with async_playwright() as playwright:
            chromium = await playwright.chromium.launch(headless=True)
            page = await chromium.new_page()
            await page.set_content(original)
            state = await page.evaluate(SAFE_LISTING_STATE_SCRIPT)
            target = state["rows"][0]
            await page.set_content(reordered)

            clicked = await click_listing_row_with_recovery(
                _PageBrowser(page), object(), target
            )

            assert clicked is False
            assert await page.evaluate("window.clicked || ''") == ""
            await chromium.close()

    asyncio.run(scenario())


def test_unique_title_recovers_when_dynamic_candidate_counter_changes():
    async def scenario():
        original = """
        <main><ul><li class="job-card">
          <button role="link" onclick="window.clicked='analyst'">ANALISTA CONTABLE</button>
          <span>5 Todos · 0 Nuevos</span><span>Bogotá</span><span>Abierto</span>
        </li></ul></main>
        """
        changed = """
        <main><ul><li class="job-card">
          <button role="link" onclick="window.clicked='analyst'">ANALISTA CONTABLE</button>
          <span>6 Todos · 1 Nuevo</span><span>Bogotá</span><span>Abierto</span>
        </li></ul></main>
        """
        async with async_playwright() as playwright:
            chromium = await playwright.chromium.launch(headless=True)
            page = await chromium.new_page()
            await page.set_content(original)
            state = await page.evaluate(SAFE_LISTING_STATE_SCRIPT)
            target = state["rows"][0]
            await page.set_content(changed)

            clicked = await click_listing_row_with_recovery(
                _PageBrowser(page), object(), target
            )

            assert clicked is True
            assert await page.evaluate("window.clicked") == "analyst"
            await chromium.close()

    asyncio.run(scenario())


def test_recycled_virtual_dom_token_cannot_click_a_different_vacancy():
    async def scenario():
        html = """
        <main><ul><li id="row" class="job-card">
          <button id="title" role="link" onclick="window.clicked=this.innerText">VACANTE A</button>
          <span>2 Todos · 1 Nuevo</span><span>Bogotá</span><span>Abierto</span>
        </li></ul></main>
        """
        async with async_playwright() as playwright:
            chromium = await playwright.chromium.launch(headless=True)
            page = await chromium.new_page()
            await page.set_content(html)
            state = await page.evaluate(SAFE_LISTING_STATE_SCRIPT)
            target = state["rows"][0]

            # Virtualized lists can reuse the same DOM node and leave custom
            # attributes behind while replacing the actual vacancy content.
            await page.evaluate(
                """() => {
                    document.querySelector('#title').innerText = 'VACANTE B';
                    document.querySelector('#row span').innerText = '9 Todos · 3 Nuevos';
                }"""
            )

            clicked = await click_listing_row_with_recovery(
                _PageBrowser(page), object(), target
            )

            assert clicked is False
            assert await page.evaluate("window.clicked || ''") == ""
            await chromium.close()

    asyncio.run(scenario())


class _CollectorBrowser:
    def __init__(self, *, detail: dict | None = None):
        self._config = SimpleNamespace(request_timeout_seconds=0.05)
        self._detail = detail

    async def _ensure_started(self):
        return object()

    async def _navigate(self, _cdp, _url):
        return None

    async def _requires_human(self, _cdp):
        return False

    async def _evaluate(self, _cdp, script):
        if script == vacancy_sync.LISTING_STATE_SCRIPT:
            return {
                "rows": [
                    {
                        "externalJobKey": "",
                        "title": "VACANTE INCOMPLETA",
                        "href": "",
                        "rowText": "VACANTE INCOMPLETA 1 Todos 0 Nuevos Bogotá Abierto",
                        "clickToken": "row-1",
                        "rowPosition": 20,
                        "listingUrl": vacancy_sync.INDEED_JOBS_URL,
                        "scrollY": 0,
                    }
                ],
                "nextHref": "",
                "scrollY": 100,
                "previousScrollY": 100,
                "viewportHeight": 600,
                "scrollHeight": 700,
            }
        if script == vacancy_sync.DETAIL_STATE_SCRIPT:
            return self._detail or {}
        if "button[aria-label*=" in script and "close" in script:
            return True
        if "window.scrollTo" in script:
            return True
        raise AssertionError(f"unexpected script: {script[:120]!r}")


def test_discovered_vacancy_that_cannot_be_opened_fails_sync_instead_of_silently_skipping(monkeypatch):
    install_vacancy_click_recovery()

    async def cannot_click(_browser, _cdp, _row):
        return False

    monkeypatch.setattr(vacancy_sync, "_click_listing_row", cannot_click)

    with pytest.raises(RuntimeError, match="^INDEED_JOB_SYNC_INCOMPLETE$"):
        asyncio.run(vacancy_sync._collect_async(_CollectorBrowser()))


def test_detail_without_stable_provider_identity_fails_sync_instead_of_silently_skipping(monkeypatch):
    install_vacancy_click_recovery()

    async def clicked(_browser, _cdp, _row):
        return True

    monkeypatch.setattr(vacancy_sync, "_click_listing_row", clicked)
    detail = {
        "url": vacancy_sync.INDEED_JOBS_URL,
        "externalJobKey": "",
        "title": "VACANTE INCOMPLETA",
        "description": "Descripción suficientemente completa para demostrar que falta únicamente la identidad.",
        "location": "Bogotá",
        "status": "Abierto",
        "postedAt": "",
        "loading": False,
    }

    with pytest.raises(RuntimeError, match="^INDEED_JOB_SYNC_INCOMPLETE$"):
        asyncio.run(vacancy_sync._collect_async(_CollectorBrowser(detail=detail)))
