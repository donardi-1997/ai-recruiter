import httpx
import pytest

from tools.indeed_resume_agent.api_client import AgentApiClient, LeaseLost
from tools.indeed_resume_agent.config import AgentConfig


def config(tmp_path):
    return AgentConfig(api_base_url="https://agent.test", browser_profile_dir=tmp_path)


def test_claim_includes_agent_token_and_parses_aware_timestamp(tmp_path):
    seen = {}
    def handler(request):
        seen["request"] = request
        return httpx.Response(200, json={
            "task_id":"t1","candidate_name":"Ada","job_title":"Engineer",
            "resume_url":"https://indeed.test/resume","lease_token":"lease-1",
            "lease_expires_at":"2026-09-17T23:00:00+00:00"
        })
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://agent.test")
    api = AgentApiClient(config(tmp_path), "a"*40, http_client=client)
    task = api.claim()
    assert seen["request"].headers["X-ASIATI-Agent-Token"] == "a"*40
    assert task.task_id == "t1"
    assert task.lease_expires_at.tzinfo is not None
    assert task.lease_expires_at.utcoffset().total_seconds() == 0


def test_claim_maps_204_to_none(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(204)), base_url="https://agent.test")
    assert AgentApiClient(config(tmp_path), "a"*40, http_client=client).claim() is None


def test_mutations_include_lease_header_and_upload_pdf_multipart(tmp_path):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={"lease_expires_at":"2026-09-17T23:05:00+00:00"})
        if request.url.path.endswith("/resume"):
            body = request.read()
            assert b'application/pdf' in body
            assert b'%PDF-test' in body
            return httpx.Response(200, json={"document_id":"d1","filename":"cv.pdf","document_sha256":"abc"})
        return httpx.Response(200, json={"status":"OK"})
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://agent.test")
    api = AgentApiClient(config(tmp_path), "a"*40, http_client=client)
    task = api._parse_claim({
        "task_id":"t1","candidate_name":"Ada","job_title":"Engineer",
        "resume_url":"https://indeed.test/resume","lease_token":"lease-1",
        "lease_expires_at":"2026-09-17T23:00:00+00:00"
    })
    api.heartbeat(task)
    api.upload_resume(task, filename="cv.pdf", data=b"%PDF-test")
    api.needs_human(task, code="CAPTCHA")
    api.fail(task, code="RESUME_DOWNLOAD_FAILED")
    for req in requests:
        assert req.headers["X-ASIATI-Agent-Token"] == "a"*40
        assert "/api/agents/indeed-resume/" in req.url.path
        assert "/candidates" not in req.url.path and "/jobs" not in req.url.path
        if req.url.path.endswith(("/heartbeat", "/resume", "/needs-human", "/fail")):
            assert req.headers["X-ASIATI-Lease-Token"] == "lease-1"


def test_stats_and_resume_after_human_use_agent_only_routes(tmp_path):
    paths=[]
    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/stats"):
            return httpx.Response(200, json={"pending":1,"claimed":0,"completed":2,"needs_human":3,"retry":4,"failed":5})
        return httpx.Response(200, json={"status":"WAITING_DOWNLOAD"})
    client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://agent.test")
    api=AgentApiClient(config(tmp_path), "a"*40, http_client=client)
    stats=api.stats()
    api.resume_after_human("t1")
    assert stats.pending == 1 and stats.needs_human == 3
    assert paths == ["/api/agents/indeed-resume/stats", "/api/agents/indeed-resume/t1/resume-after-human"]


def test_retry_failed_uses_agent_only_route_and_returns_count(tmp_path):
    paths=[]
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"status":"WAITING_DOWNLOAD","requeued":2})
    client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://agent.test")
    api=AgentApiClient(config(tmp_path), "a"*40, http_client=client)

    assert api.retry_failed() == 2
    assert paths == ["/api/agents/indeed-resume/retry-failed"]


def test_errors_are_sanitized_and_lease_conflict_is_specialized(tmp_path):
    secret_token="a"*40
    def handler(request):
        return httpx.Response(409, json={"detail":"RESUME_TASK_LEASE_EXPIRED", "resume_url":"https://secret.example"})
    client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://agent.test")
    api=AgentApiClient(config(tmp_path), secret_token, http_client=client)
    task=api._parse_claim({
        "task_id":"t1","candidate_name":"Ada","job_title":"Engineer",
        "resume_url":"https://indeed.test/resume","lease_token":"lease-secret",
        "lease_expires_at":"2026-09-17T23:00:00+00:00"
    })
    with pytest.raises(LeaseLost) as exc:
        api.heartbeat(task)
    text=str(exc.value)
    assert exc.value.status_code == 409
    assert exc.value.code == "RESUME_TASK_LEASE_EXPIRED"
    assert secret_token not in text and "lease-secret" not in text and "secret.example" not in text
