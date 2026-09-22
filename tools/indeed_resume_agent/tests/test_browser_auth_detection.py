from tools.indeed_resume_agent.browser_use_driver import IndeedBrowserUse
from tools.indeed_resume_agent.config import AgentConfig
from tools.indeed_resume_agent.runtime_compat import install_runtime_compat


def _config(tmp_path):
    return AgentConfig(
        api_base_url="https://example.com",
        browser_profile_dir=tmp_path / "profile",
        request_timeout_seconds=1.0,
    )


def test_hidden_challenge_iframe_does_not_block_authenticated_jobs(tmp_path):
    driver = IndeedBrowserUse(
        _config(tmp_path),
        browser_session_class=object,
        browser_executable_resolver=lambda: "chrome.exe",
    )
    install_runtime_compat(driver)

    async def authenticated_jobs_state(_cdp):
        return {
            "url": (
                "https://employers.indeed.com/jobs?status=open%2Cpaused"
                "&claimed=false&createdOnIndeed=true"
            ),
            "title": "Empleos - Indeed para empresas",
            "body": "Empleos Todos los empleos 407 resultados Publicar un empleo",
            "iframes": [
                {
                    "src": "https://secure.indeed.com/challenge/verify",
                    "visible": False,
                }
            ],
        }

    driver._page_state = authenticated_jobs_state
    try:
        assert driver._call(driver._requires_human(object()), timeout=2) is False
    finally:
        driver.close()


def test_authenticated_jobs_workspace_wins_over_generic_verification_copy(tmp_path):
    driver = IndeedBrowserUse(
        _config(tmp_path),
        browser_session_class=object,
        browser_executable_resolver=lambda: "chrome.exe",
    )
    install_runtime_compat(driver)

    async def authenticated_jobs_state(_cdp):
        return {
            "url": (
                "https://employers.indeed.com/jobs?status=open%2Cpaused"
                "&claimed=false&createdOnIndeed=true&tab=0"
            ),
            "title": "Empleos - Indeed para empresas",
            "body": (
                "Empleos Todos los empleos 407 resultados Publicar un empleo "
                "Ayuda sobre verificación de la cuenta"
            ),
            "iframes": [],
        }

    driver._page_state = authenticated_jobs_state
    try:
        assert driver._call(driver._requires_human(object()), timeout=2) is False
    finally:
        driver.close()


def test_visible_challenge_iframe_still_requires_human(tmp_path):
    driver = IndeedBrowserUse(
        _config(tmp_path),
        browser_session_class=object,
        browser_executable_resolver=lambda: "chrome.exe",
    )
    install_runtime_compat(driver)

    async def challenged_state(_cdp):
        return {
            "url": "https://employers.indeed.com/jobs",
            "title": "Empleos - Indeed para empresas",
            "body": "Empleos",
            "iframes": [
                {
                    "src": "https://secure.indeed.com/challenge/verify",
                    "visible": True,
                }
            ],
        }

    driver._page_state = challenged_state
    try:
        assert driver._call(driver._requires_human(object()), timeout=2) is True
    finally:
        driver.close()
