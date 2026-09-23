from playwright.sync_api import sync_playwright

from tools.indeed_resume_agent.runtime_compat import SAFE_LISTING_STATE_SCRIPT
from tools.indeed_resume_agent.vacancy_sync import (
    DETAIL_STATE_SCRIPT,
    INDEED_JOBS_URL,
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
        state = page.evaluate(SAFE_LISTING_STATE_SCRIPT)
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
        listing_state = page.evaluate(SAFE_LISTING_STATE_SCRIPT)
        page.set_content(detail_html)
        detail_state = page.evaluate(DETAIL_STATE_SCRIPT)
        browser.close()

    assert len(listing_state["rows"]) == 1
    assert listing_state["rows"][0]["externalJobKey"] == ""
    assert listing_state["rows"][0]["clickToken"]
    assert detail_state["externalJobKey"] == "job-detail-456"


def test_spa_listing_accepts_job_list_card_without_identity_until_detail():
    html = """
    <main>
      <ul>
        <li class="job-card">
          <input type="checkbox" aria-label="Seleccionar empleo" />
          <button type="button" role="link">AUXILIAR DE BODEGA</button>
          <span>12 Todos · 4 Nuevos</span>
          <span>Bogotá, Cundinamarca</span>
          <span>Abierto</span>
          <button type="button" aria-label="Más opciones">...</button>
        </li>
      </ul>
    </main>
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        state = page.evaluate(SAFE_LISTING_STATE_SCRIPT)
        browser.close()

    assert len(state["rows"]) == 1
    assert state["rows"][0]["externalJobKey"] == ""
    assert state["rows"][0]["title"] == "AUXILIAR DE BODEGA"
    assert state["rows"][0]["clickToken"]


def test_spa_listing_ignores_non_job_navigation_and_legal_links():
    html = """
    <nav>
      <ul>
        <li><a href="https://co.indeed.com/legal?hl=es&co=CO">Condiciones del servicio</a></li>
        <li><a href="https://employers.indeed.com/messages">Mensajes</a></li>
      </ul>
    </nav>
    <table>
      <tbody>
        <tr>
          <td><button type="button" role="link">VENDEDOR PUNTO DE VENTA</button></td>
          <td>7 Todos · 7 Nuevos</td>
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
        state = page.evaluate(SAFE_LISTING_STATE_SCRIPT)
        browser.close()

    assert len(state["rows"]) == 1
    assert state["rows"][0]["title"] == "VENDEDOR PUNTO DE VENTA"
    assert "Condiciones del servicio" not in [row["title"] for row in state["rows"]]
    assert "Mensajes" not in [row["title"] for row in state["rows"]]


def test_screenshot_like_workspace_extracts_only_real_jobs():
    html = """
    <nav>
      <a href="https://employers.indeed.com/messages">Mensajes</a>
      <a href="https://co.indeed.com/legal?hl=es&co=CO">Condiciones del servicio</a>
    </nav>
    <header>
      <button>Necesita revisión</button>
      <button>Estatus</button><button>Título</button><button>Ubicación</button>
      <strong>407 resultados</strong>
      <a href="https://employers.indeed.com/jobs/create">Publicar un empleo</a>
    </header>
    <div>Revisión requerida: 24 de tus empleos no son visibles para los candidatos</div>
    <main>
      <ul>
        <li class="job-card">
          <button type="button" role="link">AUXILIAR CONTABLE</button>
          <span>2 Todos · 2 Nuevos</span><span>Bogotá, Cundinamarca</span><span>Abierto</span>
        </li>
        <li class="job-card">
          <button type="button" role="link">ANALISTA CONTABLE</button>
          <span>5 Todos · 0 Nuevos</span><span>Bogotá, Cundinamarca</span><span>Abierto</span>
        </li>
        <li class="job-card">
          <button type="button" role="link">Vendedor punto de venta</button>
          <span>7 Todos · 7 Nuevos</span><span>Bogotá, Cundinamarca</span><span>Abierto</span>
        </li>
        <li class="job-card">
          <button type="button" role="link">Vendedor/cajero.</button>
          <span>11 Todos · 11 Nuevos</span><span>Bogotá, Cundinamarca</span><span>Abierto</span>
        </li>
      </ul>
    </main>
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        page.set_content(html)
        state = page.evaluate(SAFE_LISTING_STATE_SCRIPT)
        browser.close()

    titles = [row["title"] for row in state["rows"]]
    assert titles == [
        "AUXILIAR CONTABLE",
        "ANALISTA CONTABLE",
        "Vendedor punto de venta",
        "Vendedor/cajero.",
    ]
    assert "Mensajes" not in titles
    assert "Condiciones del servicio" not in titles
    assert "Publicar un empleo" not in titles


def test_safe_listing_preserves_scroll_pagination_and_row_position_for_virtualized_jobs():
    html = """
    <base href="https://employers.indeed.com/jobs?status=open%2Cpaused" />
    <main id="root">
      <ul id="jobs">
        <li class="job-card">
          <button type="button" role="link">VACANTE SUPERIOR</button>
          <span>2 Todos · 1 Nuevo</span><span>Abierto</span>
        </li>
      </ul>
      <div style="height: 2400px"></div>
      <a rel="next" href="https://employers.indeed.com/jobs?status=open%2Cpaused&page=2">Siguiente</a>
    </main>
    <script>
      window.addEventListener('scroll', () => {
        if (window.scrollY < 200 || document.getElementById('lazy-job')) return;
        const row = document.createElement('li');
        row.id = 'lazy-job';
        row.className = 'job-card';
        row.innerHTML = `
          <button type="button" role="link">VACANTE VIRTUALIZADA</button>
          <span>9 Todos · 3 Nuevos</span><span>Pausado</span>
        `;
        document.getElementById('jobs').appendChild(row);
      });
    </script>
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 600})
        page.set_content(html)
        first = page.evaluate(SAFE_LISTING_STATE_SCRIPT)
        page.wait_for_timeout(400)
        second = page.evaluate(SAFE_LISTING_STATE_SCRIPT)
        browser.close()

    assert first["scrollY"] > first["previousScrollY"]
    assert first["scrollHeight"] > first["viewportHeight"]
    assert first["nextHref"].startswith("https://employers.indeed.com/jobs")
    assert first["rows"][0]["listingUrl"].startswith("https://employers.indeed.com/jobs")
    assert "scrollY" in first["rows"][0]
    titles = {row["title"] for row in first["rows"] + second["rows"]}
    assert "VACANTE SUPERIOR" in titles
    assert "VACANTE VIRTUALIZADA" in titles


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
