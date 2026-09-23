from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright

from tools.indeed_resume_agent.indeed_jobs_current import (
    CURRENT_LISTING_STATE_SCRIPT,
    CURRENT_PAGE_STATE_SCRIPT,
    _advance_page,
    job_key_from_current_url,
)


EMPLOYER_JOB_ID = (
    "aXJpOi8vYXBpcy5pbmRlZWQuY29tL0VtcGxveWVySm9iLzQyNDVkZDYzLTQ1ZDMtNDQ0Mi05ZjM2LTYzYzRiZTYwZGE5MQ=="
)
EMPLOYER_JOB_UUID = "4245dd63-45d3-4442-9f36-63c4be60da91"
JOB_HREF = (
    "https://employers.indeed.com/jobs/view?"
    f"employerJobId={EMPLOYER_JOB_ID}&from=%253Fstatus%253Dopen"
)


def _real_row(title: str = "AUXILIAR CONTABLE", href: str = JOB_HREF) -> str:
    return f"""
    <tr data-testid="job-row">
      <td><input data-testid="job-row-checkbox" type="checkbox" /></td>
      <td>
        <span data-testid="UnifiedJobTldTitle">
          <a data-testid="UnifiedJobTldLink" href="{href}">{title}</a>
        </span>
        <div data-testid="UnifiedJobTldLocation">Bogotá, Cundinamarca</div>
      </td>
      <td>
        <button data-testid="candidates-pipeline-hosted-all-link">4 Todos</button>
        <button data-testid="candidates-pipeline-hosted-new-link">4 Nuevos</button>
      </td>
      <td data-testid="job-created-date">
        <span title="Publicado el 22 de septiembre de 2026">Hace 1 día</span>
        <span title="Publicado el 22 de septiembre de 2026">22 de septiembre de 2026</span>
      </td>
      <td>
        <div aria-label="Estado del empleo" data-testid="top-level-job-status" role="combobox">
          <span>Abierto</span>
        </div>
      </td>
    </tr>
    """


def test_current_employer_job_id_decodes_to_stable_uuid():
    assert job_key_from_current_url(JOB_HREF) == EMPLOYER_JOB_UUID


def test_current_listing_uses_unified_job_link_not_candidate_count_buttons():
    html = f"""
    <html><head>
      <base href="https://employers.indeed.com/jobs?status=open%2Cpaused" />
      <title>Empleos - Indeed para empresas</title>
    </head><body>
      <span>407 resultados</span>
      <table><tbody>{_real_row()}</tbody></table>
      <button id="ejsJobListPaginationNextBtn" aria-label="Siguiente">Siguiente</button>
    </body></html>
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        state = page.evaluate(CURRENT_LISTING_STATE_SCRIPT)
        browser.close()

    assert state["expectedTotal"] == 407
    assert state["hasNextPage"] is True
    assert state["pageSignature"] == EMPLOYER_JOB_UUID
    assert len(state["rows"]) == 1
    row = state["rows"][0]
    assert row["externalJobKey"] == EMPLOYER_JOB_UUID
    assert row["title"] == "AUXILIAR CONTABLE"
    assert row["title"] != "4 Todos"
    assert row["title"] != "4 Nuevos"
    assert row["status"] == "Abierto"
    assert row["location"] == "Bogotá, Cundinamarca"
    assert "22 de septiembre de 2026" in row["postedAt"]


def test_current_listing_ignores_auxiliary_job_rows_without_unified_job_link():
    html = f"""
    <html><head><base href="https://employers.indeed.com/jobs" /></head><body>
      <table><tbody>
        {_real_row()}
        <tr data-testid="job-row"><td>Impulsa tu publicación de empleo con esta oferta especial</td></tr>
        <tr data-testid="job-row"><td><button>Ver oferta</button></td></tr>
      </tbody></table>
    </body></html>
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        state = page.evaluate(CURRENT_LISTING_STATE_SCRIPT)
        browser.close()

    assert [row["title"] for row in state["rows"]] == ["AUXILIAR CONTABLE"]


def test_current_bootstrap_auth_is_structural_not_copy_based():
    html = """
    <html><head><title>Empleos - Indeed para empresas</title></head><body>
      <script id="one-host-bootstrap-data" type="application/json">
        {"authState":{"authType":"PASSPORT_OAUTH_PROXY","authStatus":"AUTHENTICATED"},
         "passportUser":{"isLoggedIn":true}}
      </script>
      <div>Texto auxiliar sobre verificación de empleos</div>
    </body></html>
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        state = page.evaluate(CURRENT_PAGE_STATE_SCRIPT)
        browser.close()

    assert state["authStatus"] == "AUTHENTICATED"
    assert state["isLoggedIn"] is True


def test_current_next_button_advances_when_page_signature_changes():
    async def scenario():
        async with async_playwright() as playwright:
            chromium = await playwright.chromium.launch(headless=True)
            page = await chromium.new_page()
            second_id = (
                "aXJpOi8vYXBpcy5pbmRlZWQuY29tL0VtcGxveWVySm9iL2Q5ZmU5MjQ0LWFkMjUtNDQ0MS1hMmViLTZkMTJhNGViMDY1Nw=="
            )
            second_href = (
                "https://employers.indeed.com/jobs/view?employerJobId=" + second_id
            )
            await page.set_content(
                f"""
                <html><head><base href="https://employers.indeed.com/jobs" /></head><body>
                  <table><tbody id="rows">{_real_row()}</tbody></table>
                  <button id="ejsJobListPaginationNextBtn" aria-label="Siguiente">Siguiente</button>
                </body></html>
                """
            )
            await page.evaluate(
                """
                ({ secondRowHtml }) => {
                  const button = document.getElementById('ejsJobListPaginationNextBtn');
                  button.addEventListener('click', () => {
                    document.getElementById('rows').innerHTML = secondRowHtml;
                    button.disabled = true;
                  });
                }
                """,
                {"secondRowHtml": _real_row("ANALISTA CONTABLE", second_href)},
            )

            class FakeConfig:
                request_timeout_seconds = 2

            class FakeBrowser:
                _config = FakeConfig()

                async def _evaluate(self, _cdp, script):
                    return await page.evaluate(script)

                async def _requires_human(self, _cdp):
                    return False

            first = await page.evaluate(CURRENT_LISTING_STATE_SCRIPT)
            assert first["pageSignature"] == EMPLOYER_JOB_UUID
            advanced = await _advance_page(FakeBrowser(), None, first["pageSignature"])
            second = await page.evaluate(CURRENT_LISTING_STATE_SCRIPT)
            await chromium.close()
            return advanced, first, second

    advanced, first, second = asyncio.run(scenario())
    assert advanced is True
    assert second["pageSignature"] != first["pageSignature"]
    assert second["rows"][0]["title"] == "ANALISTA CONTABLE"
    assert second["hasNextPage"] is False
