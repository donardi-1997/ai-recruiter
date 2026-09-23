from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

from tools.indeed_resume_agent.browser_use_driver import IndeedBrowserUse


CANDIDATE_ONE_ID = "5052374908d6"
CANDIDATE_TWO_ID = "ef75623665e6"


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
            _candidate_rows = IndeedBrowserUse._candidate_rows

            async def _evaluate(self, _cdp, script):
                return await page.evaluate(script)

        rows = await Harness()._candidate_rows(None)
        await chromium.close()
        return rows


def test_current_candidate_rows_extract_stable_identity_and_structured_fields():
    html = f"""
    <html><head><base href="https://employers.indeed.com/candidates" /></head><body>
      <table><tbody>
        {_candidate_row(candidate_id=CANDIDATE_ONE_ID, name="Yurani Albarracin", job_title="AUXILIAR CONTABLE")}
      </tbody></table>
    </body></html>
    """
    rows = asyncio.run(_rows_from_html(html))

    assert len(rows) == 1
    row = rows[0]
    assert row["candidateId"] == CANDIDATE_ONE_ID
    assert row["name"] == "Yurani Albarracin"
    assert row["jobTitle"] == "AUXILIAR CONTABLE"
    assert row["status"] == "Nuevos"
    assert row["appliedLabel"] == "Se postuló el Hoy"
    assert row["activity"] == "Nuevo candidato · hace 18 minutos"
    assert f"id={CANDIDATE_ONE_ID}" in row["href"]


def test_current_candidate_rows_keep_same_name_different_applications_distinct():
    html = f"""
    <html><head><base href="https://employers.indeed.com/candidates" /></head><body>
      <table><tbody>
        {_candidate_row(candidate_id=CANDIDATE_ONE_ID, name="LAURA GÓMEZ", job_title="COORDINADOR(A) ADMINISTRATIVO(A) Y DE OPERACIONES")}
        {_candidate_row(candidate_id=CANDIDATE_TWO_ID, name="LAURA GÓMEZ", job_title="Auxiliar de Selección y Reclutamiento")}
      </tbody></table>
    </body></html>
    """
    rows = asyncio.run(_rows_from_html(html))

    assert len(rows) == 2
    assert {row["candidateId"] for row in rows} == {CANDIDATE_ONE_ID, CANDIDATE_TWO_ID}
    assert {row["jobTitle"] for row in rows} == {
        "COORDINADOR(A) ADMINISTRATIVO(A) Y DE OPERACIONES",
        "Auxiliar de Selección y Reclutamiento",
    }


def test_candidate_selection_uses_structured_job_title_not_incidental_row_text():
    rows = [
        {
            "candidateId": "newer-wrong-job",
            "name": "LAURA GÓMEZ",
            "jobTitle": "Auxiliar de Selección y Reclutamiento",
            # The requested job appears elsewhere in the row text. Matching the
            # whole row would select the wrong application.
            "rowText": "LAURA GÓMEZ Auxiliar de Selección y Reclutamiento historial COORDINADOR ADMINISTRATIVO",
            "href": "https://employers.indeed.com/candidates/view?id=newer-wrong-job",
            "index": 0,
            "appliedAt": "2026-09-23T15:00:00Z",
        },
        {
            "candidateId": "older-right-job",
            "name": "LAURA GÓMEZ",
            "jobTitle": "COORDINADOR ADMINISTRATIVO",
            "rowText": "LAURA GÓMEZ COORDINADOR ADMINISTRATIVO",
            "href": "https://employers.indeed.com/candidates/view?id=older-right-job",
            "index": 1,
            "appliedAt": "2026-09-22T15:00:00Z",
        },
    ]

    target, error = IndeedBrowserUse._select_candidate(
        rows,
        "Laura Gómez",
        "COORDINADOR ADMINISTRATIVO",
    )

    assert error is None
    assert target is not None
    assert target["candidateId"] == "older-right-job"
