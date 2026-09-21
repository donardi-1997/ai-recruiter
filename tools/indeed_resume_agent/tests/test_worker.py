from datetime import datetime, timezone

from tools.indeed_resume_agent.api_client import ClaimedTask, LeaseLost
from tools.indeed_resume_agent.browser import (
    BrowserFetchStageError,
    BrowserOutcome,
    BrowserResult,
)
from tools.indeed_resume_agent.config import AgentConfig
from tools.indeed_resume_agent.worker import ResumeWorker


def task():
    return ClaimedTask(
        task_id="t1", candidate_name="Ada", job_title="Engineer",
        resume_url="https://indeed.test/resume", lease_token="lease",
        lease_expires_at=datetime(2026,9,17,23,0,tzinfo=timezone.utc),
    )


class FakeApi:
    def __init__(self, claims):
        self.claims=list(claims); self.uploads=[]; self.human=[]; self.failures=[]; self.resumed=[]; self.heartbeats=[]
    def claim(self): return self.claims.pop(0) if self.claims else None
    def upload_resume(self, t, *, filename, data): self.uploads.append((t.task_id,filename,data)); return {"document_id":"d1"}
    def needs_human(self, t, *, code): self.human.append((t.task_id,code))
    def fail(self, t, *, code): self.failures.append((t.task_id,code)); return "RETRY"
    def resume_after_human(self, task_id): self.resumed.append(task_id)
    def heartbeat(self, t): self.heartbeats.append(t.task_id); return t.lease_expires_at


class FakeBrowser:
    def __init__(self, result=None, error=None): self.result=result; self.error=error; self.urls=[]
    def fetch_resume(self, url):
        self.urls.append(url)
        if self.error: raise self.error
        return self.result


class FakeHeartbeat:
    def __init__(self, *, error=None): self.error=error; self.started=False; self.stopped=False
    def start(self): self.started=True
    def stop(self): self.stopped=True


def config(tmp_path): return AgentConfig(api_base_url="https://agent.test", browser_profile_dir=tmp_path)


def test_happy_path_claims_downloads_validates_and_uploads_once(tmp_path):
    api=FakeApi([task(), None])
    browser=FakeBrowser(BrowserResult(BrowserOutcome.DOWNLOADED, filename="ada.pdf", data=b"%PDF-ok"))
    hb=FakeHeartbeat()
    worker=ResumeWorker(config=config(tmp_path), api=api, browser=browser, heartbeat_factory=lambda **kw: hb)
    snap=worker.run_once()
    assert snap.state == "COMPLETED"
    assert snap.processed_session == 1
    assert api.uploads == [("t1","ada.pdf",b"%PDF-ok")]
    assert api.failures == [] and api.human == []
    assert hb.started and hb.stopped
    assert worker.run_once().state == "IDLE"


def test_needs_human_blocks_new_claims_until_resume(tmp_path):
    second=ClaimedTask(**{**task().__dict__, "task_id":"t2"})
    api=FakeApi([task(), second])
    browser=FakeBrowser(BrowserResult(BrowserOutcome.NEEDS_HUMAN, human_code="INDEED_AUTH_REQUIRED"))
    worker=ResumeWorker(config=config(tmp_path), api=api, browser=browser, heartbeat_factory=lambda **kw: FakeHeartbeat())
    snap=worker.run_once()
    assert snap.state == "WAITING_FOR_HUMAN"
    assert api.human == [("t1","INDEED_AUTH_REQUIRED")]
    assert worker.run_once().state == "WAITING_FOR_HUMAN"
    assert worker.human_resume_url == "https://indeed.test/resume"
    assert len(api.claims) == 1
    worker.resume()
    assert api.resumed == ["t1"]
    assert worker.human_resume_url is None
    assert len(api.claims) == 1


def test_needs_human_preserves_safe_code_without_diagnostic_path(tmp_path):
    api=FakeApi([task()])
    browser=FakeBrowser(
        BrowserResult(
            BrowserOutcome.NEEDS_HUMAN,
            human_code="INDEED_AUTH_REQUIRED",
        )
    )
    worker=ResumeWorker(
        config=config(tmp_path),
        api=api,
        browser=browser,
        heartbeat_factory=lambda **kw: FakeHeartbeat(),
    )

    snap=worker.run_once()

    assert snap.state == "WAITING_FOR_HUMAN"
    assert snap.last_error == "INDEED_AUTH_REQUIRED"
    assert api.human == [("t1","INDEED_AUTH_REQUIRED")]


def test_external_attention_retry_clears_local_human_state(tmp_path):
    api=FakeApi([task()])
    browser=FakeBrowser(BrowserResult(BrowserOutcome.NEEDS_HUMAN, human_code="INDEED_UI_REQUIRES_REVIEW"))
    worker=ResumeWorker(
        config=config(tmp_path),
        api=api,
        browser=browser,
        heartbeat_factory=lambda **kw: FakeHeartbeat(),
    )
    assert worker.run_once().state == "WAITING_FOR_HUMAN"
    assert worker.human_task_id == "t1"

    worker.reset_after_attention_retry()

    assert worker.human_task_id is None
    assert worker.human_resume_url is None
    assert worker.snapshot.state == "IDLE"


def test_heartbeat_failure_aborts_upload(tmp_path):
    api=FakeApi([task()])
    browser=FakeBrowser(BrowserResult(BrowserOutcome.DOWNLOADED, filename="ada.pdf", data=b"%PDF-ok"))
    hb=FakeHeartbeat(error=LeaseLost(409,"RESUME_TASK_LEASE_EXPIRED"))
    worker=ResumeWorker(config=config(tmp_path), api=api, browser=browser, heartbeat_factory=lambda **kw: hb)
    snap=worker.run_once()
    assert snap.state == "LEASE_LOST"
    assert api.uploads == []
    assert api.failures == []


def test_technical_browser_failure_is_reported_to_backend(tmp_path):
    api=FakeApi([task()])
    browser=FakeBrowser(error=RuntimeError("browser exploded with secret URL"))
    worker=ResumeWorker(config=config(tmp_path), api=api, browser=browser, heartbeat_factory=lambda **kw: FakeHeartbeat())
    snap=worker.run_once()
    assert snap.state == "RETRY"
    assert api.failures == [("t1","RESUME_BROWSER_FETCH_FAILED")]
    assert snap.last_error == "RESUME_BROWSER_FETCH_FAILED"
    assert "secret URL" not in (snap.last_error or "")


def test_browser_stage_failure_code_is_preserved(tmp_path):
    api=FakeApi([task()])
    browser=FakeBrowser(error=BrowserFetchStageError("RESUME_BROWSER_NAVIGATION_FAILED"))
    worker=ResumeWorker(
        config=config(tmp_path),
        api=api,
        browser=browser,
        heartbeat_factory=lambda **kw: FakeHeartbeat(),
    )
    snap=worker.run_once()
    assert snap.state == "RETRY"
    assert api.failures == [("t1","RESUME_BROWSER_NAVIGATION_FAILED")]
    assert snap.last_error == "RESUME_BROWSER_NAVIGATION_FAILED"


def test_pause_and_stop_prevent_claims(tmp_path):
    api=FakeApi([task()]); browser=FakeBrowser()
    worker=ResumeWorker(config=config(tmp_path), api=api, browser=browser, heartbeat_factory=lambda **kw: FakeHeartbeat())
    worker.pause()
    assert worker.run_once().state == "PAUSED" and len(api.claims)==1
    worker.resume()
    worker.stop()
    assert worker.run_once().state == "STOPPED" and len(api.claims)==1


def test_needs_human_surfaces_only_local_diagnostic_path(tmp_path):
    api=FakeApi([task()])
    diagnostic=str(tmp_path / "diagnostics" / "indeed-ui-review.json")
    browser=FakeBrowser(
        BrowserResult(
            BrowserOutcome.NEEDS_HUMAN,
            human_code="INDEED_UI_REQUIRES_REVIEW",
            diagnostic_path=diagnostic,
        )
    )
    worker=ResumeWorker(
        config=config(tmp_path),
        api=api,
        browser=browser,
        heartbeat_factory=lambda **kw: FakeHeartbeat(),
    )

    snap=worker.run_once()

    assert snap.state == "WAITING_FOR_HUMAN"
    assert diagnostic in (snap.last_error or "")
    assert api.human == [("t1","INDEED_UI_REQUIRES_REVIEW")]
