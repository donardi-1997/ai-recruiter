from playwright.sync_api import sync_playwright

from tools.indeed_resume_agent.vacancy_sync import (
    DETAIL_STATE_SCRIPT,
    INDEED_JOBS_URL,
    LISTING_STATE_SCRIPT,
    _job_key_from_url,
)


def test_jobs_workspace_uses_approved_open_and_paused_url():
    assert INDEED_JOBS_URL == (
        "https://employers.indeed.com/jobs?status=open%2Cpaused&claimed=false&"
        "createdOnIndeed=true&tab=0&sortDirection=DESC&sortField=datePostedOnIndeed"
    )


def test_job_key_parser_accepts_common_employer_url_shapes():
    assert _job_key_from_url("https://employers.indeed.com/jobs/view?id=ABC123") == "ABC123"
    assert _job_key_from_url("https://employers.indeed.com/jobs/view?jobId=job-456") == "job-456"
    assert _job_key_from_url("https://employers.indeed.com/jobs/job-789") == "job-789"


def test_job_key_parser_fails_closed_without_stable_identity():
    assert _job_key_from_url("https://employers.indeed.com/jobs") == ""
    assert _job_key_from_url("https://evil.example/jobs/view?id=secret") == ""


def test_spa_listing_discovers_clickable_job_without_job_href():
    html = """
    <table>
      <tbody>
        <tr data-job-id="job-abc-123">
          <td><button type="button" role="link">AUXILIAR CONTABLE</button></td>
          <td>2 Todos · 2 Nuevos</td>
          <td>Bogotá, Cundinamarca</td>
          <td>Abierto</td>
        </tr>
      </tbody>
    </table>
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        state = page.evaluate(LISTING_STATE_SCRIPT)
        browser.close()

    assert len(state["rows"]) == 1
    row = state["rows"][0]
    assert row["externalJobKey"] == "job-abc-123"
    assert row["title"] == "AUXILIAR CONTABLE"
    assert row["clickToken"]
    assert row["href"] == ""


def test_spa_listing_keeps_clickable_job_until_detail_exposes_stable_identity():
    listing_html = """
    <table>
      <tbody>
        <tr>
          <td><button type="button" role="link">ANALISTA CONTABLE</button></td>
          <td>5 Todos · 0 Nuevos</td>
          <td>Bogotá, Cundinamarca</td>
          <td>Abierto</td>
        </tr>
      </tbody>
    </table>
    """
    detail_html = """
    <aside role="dialog" data-job-id="job-detail-456">
      <h1>ANALISTA CONTABLE</h1>
      <section data-testid="job-description">
        Analizar conciliaciones, cierres y reportes contables con trazabilidad completa.
      </section>
    </aside>
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(listing_html)
        listing_state = page.evaluate(LISTING_STATE_SCRIPT)
        page.set_content(detail_html)
        detail_state = page.evaluate(DETAIL_STATE_SCRIPT)
        browser.close()

    assert len(listing_state["rows"]) == 1
    assert listing_state["rows"][0]["externalJobKey"] == ""
    assert listing_state["rows"][0]["clickToken"]
    assert detail_state["externalJobKey"] == "job-detail-456"


def test_detail_state_reports_loading_until_spa_job_detail_is_hydrated():
    loading_html = """
    <main>
      <h1>AUXILIAR CONTABLE</h1>
      <div>Cargando los detalles del empleo...</div>
    </main>
    """
    ready_html = """
    <main>
      <h1>AUXILIAR CONTABLE</h1>
      <section data-testid="job-description">
        Gestionar registros contables y conciliaciones bancarias.\n
        Preparar informes financieros mensuales para el equipo.
      </section>
    </main>
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(loading_html)
        loading_state = page.evaluate(DETAIL_STATE_SCRIPT)
        page.set_content(ready_html)
        ready_state = page.evaluate(DETAIL_STATE_SCRIPT)
        browser.close()

    assert loading_state["loading"] is True
    assert ready_state["loading"] is False
    assert ready_state["description"].startswith("Gestionar registros contables")
    assert "Preparar informes financieros" in ready_state["description"]
