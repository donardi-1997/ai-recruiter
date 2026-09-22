import httpx
import pytest

from tools.indeed_resume_agent.api_client import AgentApiClient, AgentApiError, LeaseLost
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


def test_upload_resume_preserves_docx_mime_type(tmp_path):
    seen = {}

    def handler(request):
        body = request.read()
        seen["body"] = body
        return httpx.Response(
            200,
            json={
                "document_id": "d1",
                "filename": "cv.docx",
                "document_sha256": "abc",
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://agent.test",
    )
    api = AgentApiClient(config(tmp_path), "a"*40, http_client=client)
    task = api._parse_claim({
        "task_id":"t1","candidate_name":"Ada","job_title":"Engineer",
        "resume_url":"https://indeed.test/resume","lease_token":"lease-1",
        "lease_expires_at":"2026-09-17T23:00:00+00:00"
    })

    api.upload_resume(
        task,
        filename="cv.docx",
        data=b"PK-docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert b"application/vnd.openxmlformats-officedocument.wordprocessingml.document" in seen["body"]
    assert b'filename="cv.docx"' in seen["body"]


def test_stats_and_resume_after_human_use_agent_only_routes(tmp_path):
    paths=[]
    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/stats"):
            return httpx.Response(200, json={
                "pending":1,"claimed":0,"completed":2,"needs_human":3,"retry":4,"failed":5,
                "last_error_code":"RESUME_UPLOAD_FAILED",
                "last_error_candidate":"Ada",
                "last_error_status":"FAILED",
            })
        return httpx.Response(200, json={"status":"WAITING_DOWNLOAD"})
    client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://agent.test")
    api=AgentApiClient(config(tmp_path), "a"*40, http_client=client)
    stats=api.stats()
    api.resume_after_human("t1")
    assert stats.pending == 1 and stats.needs_human == 3
    assert stats.last_error_code == "RESUME_UPLOAD_FAILED"
    assert stats.last_error_candidate == "Ada"
    assert stats.last_error_status == "FAILED"
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


def test_retry_attention_uses_agent_only_route_and_returns_count(tmp_path):
    paths=[]
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"status":"WAITING_DOWNLOAD","requeued":1})
    client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://agent.test")
    api=AgentApiClient(config(tmp_path), "a"*40, http_client=client)

    assert api.retry_attention() == 1
    assert paths == ["/api/agents/indeed-resume/retry-attention"]


def test_sync_all_exhausts_bootstrap_and_runs_incremental_catchup(tmp_path):
    calls = []
    payloads = [
        {
            "mode": "FULL",
            "discovered": 100,
            "created": 60,
            "existing": 30,
            "needs_review": 2,
            "skipped": 8,
            "has_more": True,
            "reconcile_jobs": 4,
            "reconcile_scanned": 10,
            "reconcile_ready": 4,
            "reconcile_provider_pending": 2,
            "reconcile_covered": 1,
            "reconcile_queued": 3,
        },
        {
            "mode": "FULL_CONTINUE",
            "discovered": 20,
            "created": 5,
            "existing": 10,
            "needs_review": 1,
            "skipped": 4,
            "has_more": False,
            "reconcile_jobs": 4,
            "reconcile_scanned": 10,
            "reconcile_ready": 4,
            "reconcile_provider_pending": 2,
            "reconcile_covered": 4,
            "reconcile_queued": 0,
        },
        {
            "mode": "INCREMENTAL",
            "discovered": 2,
            "created": 1,
            "existing": 1,
            "needs_review": 0,
            "skipped": 0,
            "has_more": False,
            "reconcile_jobs": 4,
            "reconcile_scanned": 10,
            "reconcile_ready": 5,
            "reconcile_provider_pending": 1,
            "reconcile_covered": 4,
            "reconcile_queued": 0,
        },
    ]

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=payloads[len(calls) - 1])

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://agent.test",
    )
    api = AgentApiClient(config(tmp_path), "a" * 40, http_client=client)

    result = api.sync_all()

    assert calls == ["/api/agents/indeed-resume/sync"] * 3
    assert result.pages == 3
    assert result.discovered == 122
    assert result.created == 66
    assert result.existing == 41
    assert result.needs_review == 3
    assert result.reconcile_jobs == 4
    assert result.reconcile_scanned == 10
    assert result.reconcile_provider_pending == 1
    assert result.reconcile_queued == 3


def test_sync_all_fails_closed_at_page_limit(tmp_path):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "mode": "FULL_CONTINUE",
                "discovered": 100,
                "created": 100,
                "existing": 0,
                "needs_review": 0,
                "skipped": 0,
                "has_more": True,
                "reconcile_jobs": 0,
                "reconcile_scanned": 0,
                "reconcile_ready": 0,
                "reconcile_provider_pending": 0,
                "reconcile_covered": 0,
                "reconcile_queued": 0,
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://agent.test",
    )
    api = AgentApiClient(config(tmp_path), "a" * 40, http_client=client)

    with pytest.raises(AgentApiError) as exc:
        api.sync_all(max_pages=2)

    assert exc.value.code == "RESUME_SYNC_PAGE_LIMIT"


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
