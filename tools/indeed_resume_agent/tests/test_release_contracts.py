from __future__ import annotations

import inspect

import httpx

from tools.indeed_resume_agent.api_client import AgentApiClient
from tools.indeed_resume_agent.config import AgentConfig
from tools.indeed_resume_agent import ui_v2


def _config(tmp_path):
    return AgentConfig(api_base_url="https://agent.test", browser_profile_dir=tmp_path)


def _command_block(source: str, start: str, end: str) -> str:
    assert start in source, f"missing command block: {start}"
    tail = source.split(start, 1)[1]
    assert end in tail, f"missing command boundary: {end}"
    return tail.split(end, 1)[0]


def test_incremental_noop_sync_all_finishes_after_one_backend_page(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "mode": "INCREMENTAL",
                "discovered": 0,
                "created": 0,
                "existing": 0,
                "needs_review": 0,
                "skipped": 0,
                "has_more": False,
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
    api = AgentApiClient(_config(tmp_path), "a" * 40, http_client=client)

    result = api.sync_all()

    assert calls == ["/api/agents/indeed-resume/sync"]
    assert result.pages == 1
    assert result.created == 0
    assert result.reconcile_scanned == 0
    assert result.reconcile_queued == 0


def test_update_vacancies_is_jobs_only_and_never_starts_application_sync():
    source = inspect.getsource(ui_v2.run_ui)
    block = _command_block(
        source,
        'elif command == "sync_jobs":',
        'elif command == "sync_all":',
    )

    assert "sync_vacancies(last_stats)" in block
    assert "api.sync_all" not in block
    assert "was_paused = worker.snapshot.state == \"PAUSED\"" in block
    assert "if not was_paused" in block


def test_full_sync_orders_vacancies_then_applications_then_worker_resume():
    source = inspect.getsource(ui_v2.run_ui)
    block = _command_block(
        source,
        'elif command == "sync_all":',
        'elif command == "retry_failed":',
    )

    jobs_position = block.index("sync_vacancies(last_stats)")
    applications_position = block.index("api.sync_all()")
    resume_position = block.index("worker.resume()")

    assert jobs_position < applications_position < resume_position
    assert '"SYNCING_APPLICATIONS"' in block
    assert '"SYNC_READY"' in block


def test_full_sync_auth_failure_does_not_resume_candidate_worker():
    source = inspect.getsource(ui_v2.run_ui)
    block = _command_block(
        source,
        'elif command == "sync_all":',
        'elif command == "retry_failed":',
    )

    try_body, except_body = block.split("except RuntimeError as exc:", 1)
    assert "worker.resume()" in try_body
    assert "worker.resume()" not in except_body
    assert 'detail == "INDEED_AUTH_REQUIRED"' in except_body


def test_sync_buttons_share_one_serial_browser_owner():
    source = inspect.getsource(ui_v2.run_ui)
    jobs_block = _command_block(
        source,
        'elif command == "sync_jobs":',
        'elif command == "sync_all":',
    )
    all_block = _command_block(
        source,
        'elif command == "sync_all":',
        'elif command == "retry_failed":',
    )

    for block in (jobs_block, all_block):
        assert "browser.diagnostic_active" in block
        assert 'worker.snapshot.state == "DOWNLOADING"' in block
        assert "worker.pause()" in block
