from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from tools.indeed_resume_agent.browser import IndeedBrowser
from tools.indeed_resume_agent.config import AgentConfig


FIXTURES = Path(__file__).parent / "fixtures" / "indeed"


def _config(tmp_path):
    return AgentConfig(
        api_base_url="https://agent.test",
        browser_profile_dir=tmp_path / "profile",
        request_timeout_seconds=3.0,
    )


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_real_playwright_candidate_search_waits_for_delayed_spa_and_opens_detail(tmp_path):
    default_html = _fixture("candidates_default.html")
    search_html = _fixture("candidates_search_delayed.html")
    detail_html = _fixture("candidate_detail.html")
    visited = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()

        def handle(route):
            url = route.request.url
            visited.append(url)
            parsed = urlsplit(url)
            if parsed.path.startswith("/candidates/view"):
                body = detail_html
            elif parsed.path == "/candidates" and parse_qs(parsed.query).get("q"):
                body = search_html
            elif parsed.path == "/candidates":
                body = default_html
            else:
                body = "<html><body>unexpected route</body></html>"
            route.fulfill(status=200, content_type="text/html", body=body)

        page.route("https://employers.indeed.com/**", handle)

        agent_browser = IndeedBrowser(_config(tmp_path))
        control, error = agent_browser._open_candidate_from_list(
            page,
            "Alejandra camacho saenz",
            job_title="Líder de Marketing y Crecimiento",
        )

        assert error is None
        assert control is not None
        assert page.url.startswith(
            "https://employers.indeed.com/candidates/view?id=alejandra"
        )
        assert any(
            "statusName=All&tab=manage&q=Alejandra+camacho+saenz" in url
            for url in visited
        )
        assert control.inner_text().strip() == "Descargar CV"
        browser.close()


def test_real_playwright_duplicate_name_is_disambiguated_by_job_title(tmp_path):
    default_html = _fixture("candidates_default.html")
    duplicate_html = _fixture("candidates_duplicate.html")
    detail_html = _fixture("candidate_detail.html")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()

        def handle(route):
            parsed = urlsplit(route.request.url)
            if parsed.path.startswith("/candidates/view"):
                body = detail_html
            elif parsed.path == "/candidates" and parse_qs(parsed.query).get("q"):
                body = duplicate_html
            else:
                body = default_html
            route.fulfill(status=200, content_type="text/html", body=body)

        page.route("https://employers.indeed.com/**", handle)

        agent_browser = IndeedBrowser(_config(tmp_path))
        control, error = agent_browser._open_candidate_from_list(
            page,
            "Alejandra Camacho Saenz",
            job_title="Lider de Marketing y Crecimiento",
        )

        assert error is None
        assert control is not None
        assert "id=alejandra-marketing" in page.url
        browser.close()
