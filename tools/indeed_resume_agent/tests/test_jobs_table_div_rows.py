from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

from tools.indeed_resume_agent.jobs_listing_compat import JOBS_LISTING_STATE_SCRIPT


HTML = """
<!doctype html>
<html>
  <head><title>Empleos - Indeed para empresas</title></head>
  <body>
    <header>
      <button>Publicar un empleo</button>
      <span>407 resultados</span>
    </header>
    <div class="jobs-grid">
      <div class="jobs-grid-header">
        <span>Título del empleo</span><span>Candidatos</span><span>Patrocinio</span>
        <span>Fecha de publicación</span><span>Email</span><span>Estado del empleo</span>
      </div>
      <div class="row-shell">
        <div><button role="link">AUXILIAR CONTABLE</button><div>Bogotá, Cundinamarca</div></div>
        <div>3</div><div>No</div><div>22 sep</div><div>—</div><div>Abierto</div>
      </div>
      <div class="row-shell">
        <div><button role="link">ANALISTA CONTABLE</button><div>Bogotá, Cundinamarca</div></div>
        <div>8</div><div>No</div><div>21 sep</div><div>—</div><div>Pausado</div>
      </div>
    </div>
    <footer>
      <a href="https://co.indeed.com/legal">Condiciones del servicio</a>
      <button role="link">Mensajes</button>
    </footer>
  </body>
</html>
"""


def test_jobs_workspace_div_rows_are_detected_without_row_roles_or_job_testids():
    async def scenario():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(HTML)

            state = await page.evaluate(JOBS_LISTING_STATE_SCRIPT)

            titles = [row["title"] for row in state["rows"]]
            assert titles == ["AUXILIAR CONTABLE", "ANALISTA CONTABLE"]
            assert "Condiciones del servicio" not in titles
            assert "Mensajes" not in titles
            await browser.close()

    asyncio.run(scenario())
