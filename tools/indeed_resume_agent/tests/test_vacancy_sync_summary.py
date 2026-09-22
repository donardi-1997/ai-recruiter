import httpx

from tools.indeed_resume_agent.api_client import AgentApiClient
from tools.indeed_resume_agent.config import AgentConfig
from tools.indeed_resume_agent.ui_v2 import _vacancy_summary


def test_vacancy_sync_parses_and_surfaces_recovered_applications(tmp_path):
    payload = {
        "discovered": 12,
        "created": 2,
        "updated": 3,
        "reconciled": 1,
        "unchanged": 6,
        "missing_identity": 0,
        "missing_description": 0,
        "ambiguous": 0,
        "descriptions_recovered": 4,
        "applications_recovered": 5,
    }

    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
        base_url="https://agent.test",
    )
    config = AgentConfig(
        api_base_url="https://agent.test",
        browser_profile_dir=tmp_path,
    )
    api = AgentApiClient(config, "a" * 40, http_client=client)

    result = api.sync_jobs([])

    assert result.applications_recovered == 5
    summary = _vacancy_summary(result)
    assert "5 postulaciones recuperadas" in summary
