from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

from tools.indeed_resume_agent.indeed_candidates_current import _scan_candidate_search


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
                "https://employers.indeed.com/candidates/view**",
                lambda route: route.fulfill(
                    status=200,
                    content_type="text/html",
                    body="""
                    <html><body>
                      <h1>Candidata Target</h1>
                      <div>Postulado a VACANTE TARGET</div>
                      <button>Descargar CV</button>
                    </body></html>
                    """,
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
