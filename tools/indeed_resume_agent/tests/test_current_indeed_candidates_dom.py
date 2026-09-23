from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

from tools.indeed_resume_agent.indeed_candidates_current import (
    CURRENT_CANDIDATE_DETAIL_SCRIPT,
    CURRENT_CANDIDATE_LIST_SCRIPT,
    _advance_candidate_page,
    candidate_id_from_url,
    install_current_indeed_candidates,
    select_current_candidate,
)


CANDIDATE_ONE_ID = "candidate-alpha-001"
CANDIDATE_TWO_ID = "candidate-beta-002"


def _candidate_row(
    *,
    candidate_id: str,
    name: str,
    job_title: str,
    status: str = "Nuevos",
    applied: str = "Se postuló el Hoy",
    activity: str = "Nuevo candidato · hace 18 minutos",
) -> str:
    return f"""
    <tr role="row">
      <td>
        <h2 data-testid="CandidateInfoColumnCell">
          <a data-testid="NameCell" role="link"
             href="/candidates/view?id={candidate_id}&l=l74l&legacyJobId=0">{name}</a>
        </h2>
        <span data-testid="CandidateInfoColumn-location">Bogotá</span>
        <div data-testid="CandidateInfoColumn-status-apply">
          <span data-testid="CandidateInfoColumn-status">{status}</span>
          <span data-testid="CandidateInfoColumn-apply">{applied}</span>
        </div>
        <div data-testid="CandidateInfoColumn-job-applied-to">
          Empleo al que se postuló: {job_title}
        </div>
      </td>
      <td><div data-testid="candidate-matches-to-job-post">Sin coincidencias</div></td>
      <td><div data-testid="stackable-guided-nudge">{activity}</div></td>
      <td><button data-testid="candidate-actions-dropdown">...</button></td>
    </tr>
    """


async def _rows_from_html(html: str) -> list[dict]:
    async with async_playwright() as playwright:
        chromium = await playwright.chromium.launch(headless=True)
        page = await chromium.new_page()
        await page.set_content(html)

        class Harness:
            async def _evaluate(self, _cdp, script):
                return await page.evaluate(script)

        harness = Harness()
        install_current_indeed_candidates(harness)
        rows = await harness._candidate_rows(None)
        await chromium.close()
        return rows


def test_current_candidate_rows_extract_stable_identity_and_structured_fields():
    html = f"""
    <html><head><base href="https://employers.indeed.com/candidates" /></head><body>
      <table><tbody>
        {_candidate_row(candidate_id=CANDIDATE_ONE_ID, name="Candidata Alpha", job_title="VACANTE ALPHA")}
      </tbody></table>
    </body></html>
    """
    rows = asyncio.run(_rows_from_html(html))

    assert len(rows) == 1
    row = rows[0]
    assert row["candidateId"] == CANDIDATE_ONE_ID
    assert row["name"] == "Candidata Alpha"
    assert row["jobTitle"] == "VACANTE ALPHA"
    assert row["status"] == "Nuevos"
    assert row["appliedLabel"] == "Se postuló el Hoy"
    assert row["activity"] == "Nuevo candidato · hace 18 minutos"
    assert f"id={CANDIDATE_ONE_ID}" in row["href"]


def test_current_candidate_rows_keep_same_name_different_applications_distinct():
    html = f"""
    <html><head><base href="https://employers.indeed.com/candidates" /></head><body>
      <table><tbody>
        {_candidate_row(candidate_id=CANDIDATE_ONE_ID, name="Candidata Duplicada", job_title="VACANTE ALPHA")}
        {_candidate_row(candidate_id=CANDIDATE_TWO_ID, name="Candidata Duplicada", job_title="VACANTE BETA")}
      </tbody></table>
    </body></html>
    """
    rows = asyncio.run(_rows_from_html(html))

    assert len(rows) == 2
    assert {row["candidateId"] for row in rows} == {CANDIDATE_ONE_ID, CANDIDATE_TWO_ID}
    assert {row["jobTitle"] for row in rows} == {"VACANTE ALPHA", "VACANTE BETA"}


def test_candidate_selection_uses_structured_job_title_not_incidental_row_text():
    rows = [
        {
            "candidateId": "newer-wrong-job",
            "name": "Candidata Duplicada",
            "jobTitle": "VACANTE BETA",
            # The requested job appears elsewhere in the row text. Matching the
            # whole row would select the wrong application.
            "rowText": "Candidata Duplicada VACANTE BETA historial VACANTE ALPHA",
            "href": "https://employers.indeed.com/candidates/view?id=newer-wrong-job",
            "index": 0,
            "appliedAt": "2026-09-23T15:00:00Z",
        },
        {
            "candidateId": "older-right-job",
            "name": "Candidata Duplicada",
            "jobTitle": "VACANTE ALPHA",
            "rowText": "Candidata Duplicada VACANTE ALPHA",
            "href": "https://employers.indeed.com/candidates/view?id=older-right-job",
            "index": 1,
            "appliedAt": "2026-09-22T15:00:00Z",
        },
    ]

    target, error = select_current_candidate(
        rows,
        "Candidata Duplicada",
        "VACANTE ALPHA",
    )

    assert error is None
    assert target is not None
    assert target["candidateId"] == "older-right-job"


def test_candidate_id_parser_accepts_only_current_indeed_detail_route():
    assert candidate_id_from_url(
        f"https://employers.indeed.com/candidates/view?id={CANDIDATE_ONE_ID}&l=l74l"
    ) == CANDIDATE_ONE_ID
    assert candidate_id_from_url(
        f"https://evil.example/candidates/view?id={CANDIDATE_ONE_ID}"
    ) == ""
    assert candidate_id_from_url(
        f"https://employers.indeed.com/candidates?id={CANDIDATE_ONE_ID}"
    ) == ""


def test_current_candidate_list_reports_real_total_and_next_button():
    async def scenario():
        async with async_playwright() as playwright:
            chromium = await playwright.chromium.launch(headless=True)
            page = await chromium.new_page()
            await page.set_content(
                f"""
                <html><head><base href="https://employers.indeed.com/candidates" /></head><body>
                  <table><tbody>{_candidate_row(candidate_id=CANDIDATE_ONE_ID, name="Candidata Alpha", job_title="VACANTE ALPHA")}</tbody></table>
                  <button aria-disabled="true">Anterior</button>
                  <button aria-disabled="false">Siguiente</button>
                  <span>Mostrando 1 a 20 de 27878</span>
                </body></html>
                """
            )
            state = await page.evaluate(CURRENT_CANDIDATE_LIST_SCRIPT)
            await chromium.close()
            return state

    state = asyncio.run(scenario())
    assert state["expectedTotal"] == 27878
    assert state["hasNextPage"] is True
    assert state["pageSignature"] == CANDIDATE_ONE_ID


def test_current_candidate_next_button_advances_when_page_signature_changes():
    async def scenario():
        async with async_playwright() as playwright:
            chromium = await playwright.chromium.launch(headless=True)
            page = await chromium.new_page()
            await page.set_content(
                f"""
                <html><head><base href="https://employers.indeed.com/candidates" /></head><body>
                  <table><tbody id="rows">{_candidate_row(candidate_id=CANDIDATE_ONE_ID, name="Candidata Alpha", job_title="VACANTE ALPHA")}</tbody></table>
                  <button aria-disabled="true">Anterior</button>
                  <button id="next" aria-disabled="false">Siguiente</button>
                  <span>Mostrando 1 a 20 de 40</span>
                </body></html>
                """
            )
            await page.evaluate(
                """
                ({ secondRowHtml }) => {
                  const button = document.getElementById('next');
                  button.addEventListener('click', () => {
                    document.getElementById('rows').innerHTML = secondRowHtml;
                    button.setAttribute('aria-disabled', 'true');
                  });
                }
                """,
                {
                    "secondRowHtml": _candidate_row(
                        candidate_id=CANDIDATE_TWO_ID,
                        name="Candidata Beta",
                        job_title="VACANTE BETA",
                    )
                },
            )

            class FakeConfig:
                request_timeout_seconds = 2

            class FakeBrowser:
                _config = FakeConfig()

                async def _evaluate(self, _cdp, script):
                    return await page.evaluate(script)

                async def _requires_human(self, _cdp):
                    return False

            first = await page.evaluate(CURRENT_CANDIDATE_LIST_SCRIPT)
            advanced = await _advance_candidate_page(
                FakeBrowser(), None, first["pageSignature"]
            )
            second = await page.evaluate(CURRENT_CANDIDATE_LIST_SCRIPT)
            await chromium.close()
            return advanced, first, second

    advanced, first, second = asyncio.run(scenario())
    assert advanced is True
    assert second["pageSignature"] != first["pageSignature"]
    assert second["rows"][0]["candidateId"] == CANDIDATE_TWO_ID
    assert second["hasNextPage"] is False


def test_current_candidate_detail_verifies_identity_and_download_control():
    async def scenario():
        async with async_playwright() as playwright:
            chromium = await playwright.chromium.launch(headless=True)
            page = await chromium.new_page()
            detail_url = (
                "https://employers.indeed.com/candidates/view?"
                f"id={CANDIDATE_ONE_ID}&l=l74l"
            )
            await page.route(
                "https://employers.indeed.com/**",
                lambda route: route.fulfill(
                    status=200,
                    content_type="text/html",
                    body="""
                    <html><head><title>Candidatos - Indeed para empresas</title></head><body>
                      <h1>Candidata Detalle</h1>
                      <div>Postulado a VACANTE ALPHA</div>
                      <button>Descargar CV</button>
                      <h2>Currículum</h2>
                    </body></html>
                    """,
                ),
            )
            await page.goto(detail_url)
            state = await page.evaluate(CURRENT_CANDIDATE_DETAIL_SCRIPT)
            await chromium.close()
            return state

    state = asyncio.run(scenario())
    assert state["candidateId"] == CANDIDATE_ONE_ID
    assert state["heading"] == "Candidata Detalle"
    assert state["downloadReady"] is True
    assert "Postulado a VACANTE ALPHA" in state["body"]
