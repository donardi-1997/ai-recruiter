from tools.indeed_resume_agent.tests.test_worker import (
    FakeApi,
    FakeBrowser,
    FakeHeartbeat,
    config,
    task,
)
from tools.indeed_resume_agent.worker import ResumeWorker


def _run_browser_error(tmp_path, error: Exception):
    api = FakeApi([task()])
    browser = FakeBrowser(error=error)
    worker = ResumeWorker(
        config=config(tmp_path),
        api=api,
        browser=browser,
        heartbeat_factory=lambda **kw: FakeHeartbeat(),
    )
    return worker.run_once(), api, browser


def test_browser_timeout_is_reported_with_specific_safe_code(tmp_path):
    snap, api, browser = _run_browser_error(
        tmp_path,
        TimeoutError("BROWSER_USE_OPERATION_TIMEOUT"),
    )

    assert snap.state == "RETRY"
    assert snap.last_error == "RESUME_BROWSER_TIMEOUT"
    assert api.failures == [("t1", "RESUME_BROWSER_TIMEOUT")]
    assert browser.reset_calls == 1


def test_safe_symbolic_runtime_error_is_preserved_without_freeform_text(tmp_path):
    snap, api, _browser = _run_browser_error(
        tmp_path,
        RuntimeError("INDEED_AUTH_REQUIRED"),
    )

    assert snap.last_error == "RESUME_BROWSER_INDEED_AUTH_REQUIRED"
    assert api.failures == [("t1", "RESUME_BROWSER_INDEED_AUTH_REQUIRED")]


def test_freeform_runtime_error_remains_generic_and_does_not_leak_details(tmp_path):
    snap, api, _browser = _run_browser_error(
        tmp_path,
        RuntimeError("browser exploded at https://secret.example/?token=abc"),
    )

    assert snap.last_error == "RESUME_BROWSER_FETCH_FAILED"
    assert api.failures == [("t1", "RESUME_BROWSER_FETCH_FAILED")]
    assert "secret.example" not in (snap.last_error or "")
    assert "token" not in (snap.last_error or "")
