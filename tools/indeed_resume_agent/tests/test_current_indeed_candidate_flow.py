from __future__ import annotations

import asyncio
import re

from playwright.async_api import async_playwright

from tools.indeed_resume_agent.indeed_candidates_current import (
    CURRENT_CANDIDATE_DETAIL_SCRIPT,
    _open_candidate_current,
    _open_selected_candidate,
    _scan_candidate_search,
)


FIRST_ID = "candidate-page-one"
TARGET_ID = "candidate-page-two"


def _row(candidate_id: str, name: str, job_title: str) -> str:
    return f"""
    <tr role="row">
      <td>
        <a data-testid="NameCell" href="/candidates/view?id={candidate_id}">{name}</a>
        <div data-testid="CandidateInfoColumn-job-applied-to">Empleo al que se postuló: {job_title}</div>
        <span data-testid="CandidateInfoColumn-status">Nuevos</span>
        <span data-testid="CandidateInfoColumn-apply">Se postuló el Hoy</span>
      </td>
      <td><div data-testid="stackable-guided-nudge">Nuevo candidato · hace 10 minutos</div></td>
    </tr>
    """


def _detail(name: str, job_title: str) -> str:
    return f"""
    <html><body>
      <div id="candidateProfileContainer">
        <div data-testid="namePlate">
          <div data-testid="name-plate-name-item"><h1>{name}</h1></div>
        </div>
        <a href="/jobs/view?employerJobId=job-target">{job_title} • Bogotá</a>
        <button data-testid="download-resume-inline">Descargar HV</button>
      </div>
    </body></html>
    """


def test_candidate_scan_paginates_then_opens_the_exact_application_detail():
    async def scenario():
        async with async_playwright() as playwright:
            chromium = await playwright.chromium.launch(headless=True)
            page = await chromium.new_page()
            await page.set_content(
                f"""
                <html><head><base href="https://employers.indeed.com/candidates" /></head><body>
                  <table><tbody id="rows">{_row(FIRST_ID, 'Otra Persona', 'VACANTE OTRA')}</tbody></table>
                  <button id="next" aria-disabled="false">Siguiente</button>
                  <span>Mostrando 1 a 20 de 40</span>
                </body></html>
                """
            )
            await page.evaluate(
                """
                ({ targetRow }) => {
                  const next = document.getElementById('next');
                  next.addEventListener('click', () => {
                    document.getElementById('rows').innerHTML = targetRow;
                    next.setAttribute('aria-disabled', 'true');
                  });
                }
                """,
                {"targetRow": _row(TARGET_ID, "Candidata Target", "VACANTE TARGET")},
            )
            await page.route(
                re.compile(r"https://employers\.indeed\.com/candidates/view\?.*"),
                lambda route: route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body=_detail("Candidata Target", "VACANTE TARGET"),
                ),
            )

            class Config:
                request_timeout_seconds = 2

            class Browser:
                _config = Config()

                async def _evaluate(self, _cdp, script):
                    return await page.evaluate(script)

                async def _requires_human(self, _cdp):
                    return False

                async def _navigate(self, _cdp, url):
                    await page.goto(url)

            result = await _scan_candidate_search(
                Browser(), None, "Candidata Target", "VACANTE TARGET"
            )
            final_url = page.url
            await chromium.close()
            return result, final_url

    result, final_url = asyncio.run(scenario())
    assert result is None
    assert f"id={TARGET_ID}" in final_url


def test_open_candidate_stops_after_verified_detail_instead_of_searching_again():
    async def scenario():
        async with async_playwright() as playwright:
            chromium = await playwright.chromium.launch(headless=True)
            page = await chromium.new_page()
            list_body = f"""
                <html><body>
                  <table><tbody>{_row(TARGET_ID, 'Candidata Target', 'VACANTE TARGET')}</tbody></table>
                  <button aria-disabled="true">Siguiente</button>
                  <span>Mostrando 1 a 1 de 1</span>
                </body></html>
            """
            await page.route(
                re.compile(r"https://employers\.indeed\.com/candidates\?.*"),
                lambda route: route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body=list_body,
                ),
            )
            await page.route(
                re.compile(r"https://employers\.indeed\.com/candidates/view\?.*"),
                lambda route: route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body=_detail("Candidata Target", "VACANTE TARGET"),
                ),
            )

            class Config:
                request_timeout_seconds = 2

            class Browser:
                _config = Config()

                def __init__(self):
                    self.fill_calls = 0

                async def _evaluate(self, _cdp, script):
                    return await page.evaluate(script)

                async def _requires_human(self, _cdp):
                    return False

                async def _navigate(self, _cdp, url):
                    await page.goto(url)

                async def _fill_candidate_search(self, _cdp, _query):
                    self.fill_calls += 1
                    return False

            browser = Browser()
            result = await _open_candidate_current(
                browser, None, "Candidata Target", "VACANTE TARGET"
            )
            final_url = page.url
            fill_calls = browser.fill_calls
            await chromium.close()
            return result, final_url, fill_calls

    result, final_url, fill_calls = asyncio.run(scenario())
    assert result is None
    assert f"id={TARGET_ID}" in final_url
    assert fill_calls == 0


def test_open_selected_candidate_waits_for_matching_panel_content_after_url_changes():
    class Config:
        request_timeout_seconds = 2

    class Browser:
        _config = Config()

        def __init__(self):
            self.detail_evaluations = 0

        async def _navigate(self, _cdp, _url):
            return None

        async def _requires_human(self, _cdp):
            return False

        async def _evaluate(self, _cdp, script):
            assert script == CURRENT_CANDIDATE_DETAIL_SCRIPT
            self.detail_evaluations += 1
            if self.detail_evaluations == 1:
                return {
                    "candidateId": TARGET_ID,
                    "heading": "Candidata Anterior",
                    "jobTitle": "VACANTE ANTERIOR",
                    "body": "VACANTE ANTERIOR Descargar HV",
                    "downloadReady": True,
                }
            return {
                "candidateId": TARGET_ID,
                "heading": "Candidata Target",
                "jobTitle": "VACANTE TARGET",
                "body": "VACANTE TARGET Descargar HV",
                "downloadReady": True,
            }

    async def scenario():
        browser = Browser()
        result = await _open_selected_candidate(
            browser,
            None,
            {
                "candidateId": TARGET_ID,
                "name": "Candidata Target",
                "jobTitle": "VACANTE TARGET",
                "href": f"https://employers.indeed.com/candidates/view?id={TARGET_ID}",
            },
        )
        return result, browser.detail_evaluations

    result, detail_evaluations = asyncio.run(scenario())
    assert result is None
    assert detail_evaluations >= 2


def test_detail_script_reads_current_profile_job_and_descargar_hv_control():
    async def scenario():
        async with async_playwright() as playwright:
            chromium = await playwright.chromium.launch(headless=True)
            page = await chromium.new_page()
            await page.route(
                re.compile(r"https://employers\.indeed\.com/candidates/view\?.*"),
                lambda route: route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body=_detail("Candidata Target", "VACANTE TARGET"),
                ),
            )
            await page.goto(
                f"https://employers.indeed.com/candidates/view?id={TARGET_ID}"
            )
            detail = await page.evaluate(CURRENT_CANDIDATE_DETAIL_SCRIPT)
            await chromium.close()
            return detail

    detail = asyncio.run(scenario())
    assert detail["candidateId"] == TARGET_ID
    assert detail["heading"] == "Candidata Target"
    assert detail["jobTitle"] == "VACANTE TARGET"
    assert detail["downloadReady"] is True
