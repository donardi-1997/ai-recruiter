import asyncio

from playwright.sync_api import sync_playwright

from tools.indeed_resume_agent import vacancy_sync
from tools.indeed_resume_agent.runtime_compat import SAFE_LISTING_STATE_SCRIPT


def test_safe_listing_marks_the_exact_token_consumed_by_spa_clicker():
    html = """
    <table><tbody>
      <tr>
        <td><button type="button" role="link">ANALISTA DE DATOS</button></td>
        <td>5 Todos · 2 Nuevos</td>
        <td>Bogotá, Cundinamarca</td>
        <td>Abierto</td>
      </tr>
    </tbody></table>
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        state = page.evaluate(SAFE_LISTING_STATE_SCRIPT)
        assert len(state["rows"]) == 1
        token = state["rows"][0]["clickToken"]
        marked = page.locator(f'[data-asiati-vacancy-token="{token}"]')
        assert marked.count() == 1
        assert marked.first.inner_text() == "ANALISTA DE DATOS"
        browser.close()


def test_spa_clicker_recovers_exact_duplicate_row_after_listing_reload_loses_token():
    html = """
    <main>
      <ul>
        <li class="job-card">
          <button type="button" role="link" onclick="window.clicked='first'">ASESOR COMERCIAL</button>
          <span>0 Todos · 0 Nuevos</span>
          <span>Bogotá, Cundinamarca</span>
          <span>Abierto</span>
        </li>
        <li class="job-card">
          <button type="button" role="link" onclick="window.clicked='second'">ASESOR COMERCIAL</button>
          <span>0 Todos · 0 Nuevos</span>
          <span>Bogotá, Cundinamarca</span>
          <span>Abierto</span>
        </li>
      </ul>
    </main>
    """

    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch(headless=True)
        page = chromium.new_page()
        page.set_content(html)
        state = page.evaluate(SAFE_LISTING_STATE_SCRIPT)
        assert len(state["rows"]) == 2
        target = state["rows"][1]

        # A real listing navigation/reload removes the temporary token attributes.
        page.set_content(html)

        class Browser:
            async def _evaluate(self, _cdp, script):
                return page.evaluate(script)

        clicked = asyncio.run(vacancy_sync._click_listing_row(Browser(), object(), target))

        assert clicked is True
        assert page.evaluate("window.clicked") == "second"
        chromium.close()
