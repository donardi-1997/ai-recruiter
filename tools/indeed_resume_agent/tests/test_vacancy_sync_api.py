import httpx

from tools.indeed_resume_agent.api_client import AgentApiClient
from tools.indeed_resume_agent.config import AgentConfig


def config(tmp_path):
    return AgentConfig(api_base_url="https://agent.test", browser_profile_dir=tmp_path)


def test_sync_jobs_posts_snapshots_and_returns_delta_summary(tmp_path):
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["token"] = request.headers.get("X-ASIATI-Agent-Token")
        seen["payload"] = request.read().decode("utf-8")
        return httpx.Response(
            200,
            json={
                "discovered": 4,
                "created": 1,
                "updated": 2,
                "reconciled": 0,
                "unchanged": 1,
                "missing_identity": 0,
                "missing_description": 0,
                "ambiguous": 0,
                "descriptions_recovered": 1,
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://agent.test",
    )
    api = AgentApiClient(config(tmp_path), "a" * 40, http_client=client)

    result = api.sync_jobs([
        {
            "external_job_key": "job-1",
            "title": "Cloud Engineer",
            "description": "Complete description",
            "status": "OPEN",
            "location": "Bogotá",
            "posted_at": None,
        }
    ])

    assert seen["path"] == "/api/agents/indeed-resume/jobs/sync"
    assert seen["token"] == "a" * 40
    assert '"external_job_key":"job-1"' in seen["payload"].replace(" ", "")
    assert result.discovered == 4
    assert result.created == 1
    assert result.updated == 2
    assert result.unchanged == 1
    assert result.descriptions_recovered == 1
