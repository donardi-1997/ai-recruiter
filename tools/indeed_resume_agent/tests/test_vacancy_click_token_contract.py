from playwright.sync_api import sync_playwright

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
