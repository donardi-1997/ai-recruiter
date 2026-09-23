import asyncio

from playwright.async_api import async_playwright

from tools.indeed_resume_agent import vacancy_sync
from tools.indeed_resume_agent.runtime_compat import SAFE_LISTING_STATE_SCRIPT
from tools.indeed_resume_agent.vacancy_click_recovery import install_vacancy_click_recovery


def test_safe_listing_marks_the_exact_token_consumed_by_spa_clicker():
    async def scenario():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(
                """
                <table><tbody>
                  <tr>
                    <td><button type="button" role="link">ANALISTA DE DATOS</button></td>
                    <td>5 Todos · 2 Nuevos</td>
                    <td>Bogotá, Cundinamarca</td>
                    <td>Abierto</td>
                  </tr>
                </tbody></table>
                """
            )
            state = await page.evaluate(SAFE_LISTING_STATE_SCRIPT)
            assert len(state["rows"]) == 1
            token = state["rows"][0]["clickToken"]
            marked = page.locator(f'[data-asiati-vacancy-token="{token}"]')
            assert await marked.count() == 1
            assert await marked.first.inner_text() == "ANALISTA DE DATOS"
            await browser.close()

    asyncio.run(scenario())


def test_spa_clicker_fails_closed_for_exact_duplicates_after_reload_loses_token():
    async def scenario():
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

        install_vacancy_click_recovery()
        async with async_playwright() as playwright:
            chromium = await playwright.chromium.launch(headless=True)
            page = await chromium.new_page()
            await page.set_content(html)
            state = await page.evaluate(SAFE_LISTING_STATE_SCRIPT)
            assert len(state["rows"]) == 2
            target = state["rows"][1]

            # A real listing navigation/reload removes the temporary token attributes.
            # With no stable provider id, two visually identical publications cannot
            # be distinguished safely and must not be guessed from row position.
            await page.set_content(html)

            class Browser:
                async def _evaluate(self, _cdp, script):
                    return await page.evaluate(script)

            clicked = await vacancy_sync._click_listing_row(Browser(), object(), target)

            assert clicked is False
            assert await page.evaluate("window.clicked || ''") == ""
            await chromium.close()

    asyncio.run(scenario())
