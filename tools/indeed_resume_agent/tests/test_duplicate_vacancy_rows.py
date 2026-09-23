from playwright.sync_api import sync_playwright

from tools.indeed_resume_agent.runtime_compat import SAFE_LISTING_STATE_SCRIPT


def test_two_identical_visible_vacancy_rows_are_not_collapsed_before_detail_identity():
    html = """
    <main>
      <ul>
        <li class="job-card">
          <button type="button" role="link">ASESOR COMERCIAL</button>
          <span>0 Todos · 0 Nuevos</span>
          <span>Bogotá, Cundinamarca</span>
          <span>Abierto</span>
        </li>
        <li class="job-card">
          <button type="button" role="link">ASESOR COMERCIAL</button>
          <span>0 Todos · 0 Nuevos</span>
          <span>Bogotá, Cundinamarca</span>
          <span>Abierto</span>
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

    assert len(state["rows"]) == 2
    assert [row["title"] for row in state["rows"]] == [
        "ASESOR COMERCIAL",
        "ASESOR COMERCIAL",
    ]
    assert state["rows"][0]["externalJobKey"] == ""
    assert state["rows"][1]["externalJobKey"] == ""
    assert state["rows"][0]["clickToken"] != state["rows"][1]["clickToken"]
