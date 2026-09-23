from tools.indeed_resume_agent.browser_use_driver import IndeedBrowserUse
from tools.indeed_resume_agent.config import AgentConfig
from tools.indeed_resume_agent.runtime_compat import install_runtime_compat


def _config(tmp_path):
    return AgentConfig(
        api_base_url="https://example.com",
        browser_profile_dir=tmp_path / "profile",
        request_timeout_seconds=1.0,
    )


def _driver(tmp_path):
    driver = IndeedBrowserUse(
        _config(tmp_path),
        browser_session_class=object,
        browser_executable_resolver=lambda: "chrome.exe",
    )
    install_runtime_compat(driver)
    return driver


def test_hidden_challenge_iframe_does_not_block_authenticated_jobs(tmp_path):
    driver = _driver(tmp_path)

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
    driver = _driver(tmp_path)

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


def test_authenticated_candidates_workspace_does_not_false_positive_on_verification_copy(tmp_path):
    driver = _driver(tmp_path)

    async def authenticated_candidates_state(_cdp):
        return {
            "url": (
                "https://employers.indeed.com/candidates"
                "?statusName=All&tab=manage&q=Adrian+Guerra"
            ),
            "title": "Candidatos - Indeed para empresas",
            "body": (
                "Candidatos Buscar candidatos Todos los candidatos "
                "Ayuda sobre verificación de la cuenta"
            ),
            "iframes": [],
        }

    driver._page_state = authenticated_candidates_state
    try:
        assert driver._call(driver._requires_human(object()), timeout=2) is False
    finally:
        driver.close()


def test_authenticated_candidate_detail_does_not_false_positive_on_verification_copy(tmp_path):
    driver = _driver(tmp_path)

    async def authenticated_candidate_state(_cdp):
        return {
            "url": "https://employers.indeed.com/candidates/view/abc123",
            "title": "Candidato - Indeed para empresas",
            "body": (
                "Candidato Hoja de vida Descargar CV Mensajes "
                "Ayuda sobre verificación de la cuenta"
            ),
            "iframes": [],
        }

    driver._page_state = authenticated_candidate_state
    try:
        assert driver._call(driver._requires_human(object()), timeout=2) is False
    finally:
        driver.close()


def test_visible_challenge_iframe_still_requires_human(tmp_path):
    driver = _driver(tmp_path)

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


def test_explicit_challenge_url_still_requires_human(tmp_path):
    driver = _driver(tmp_path)

    async def challenged_state(_cdp):
        return {
            "url": "https://secure.indeed.com/challenge/verify?continue=/candidates",
            "title": "Indeed",
            "body": "",
            "iframes": [],
        }

    driver._page_state = challenged_state
    try:
        assert driver._call(driver._requires_human(object()), timeout=2) is True
    finally:
        driver.close()


def test_explicit_login_copy_still_requires_human(tmp_path):
    driver = _driver(tmp_path)

    async def login_state(_cdp):
        return {
            "url": "https://employers.indeed.com/candidates",
            "title": "Indeed",
            "body": "Iniciar sesión para continuar",
            "iframes": [],
        }

    driver._page_state = login_state
    try:
        assert driver._call(driver._requires_human(object()), timeout=2) is True
    finally:
        driver.close()
