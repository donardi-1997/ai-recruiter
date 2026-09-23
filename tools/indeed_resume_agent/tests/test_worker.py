from datetime import datetime, timezone
import io
import zipfile

from tools.indeed_resume_agent.api_client import ClaimedTask, LeaseLost
from tools.indeed_resume_agent.browser import (
    BrowserFetchStageError,
    BrowserOutcome,
    BrowserResult,
    DOCX_CONTENT_TYPE,
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
    def upload_resume(self, t, *, filename, data, content_type="application/pdf"):
        self.uploads.append((t.task_id,filename,data,content_type))
        return {"document_id":"d1"}
    def needs_human(self, t, *, code): self.human.append((t.task_id,code))
    def fail(self, t, *, code): self.failures.append((t.task_id,code)); return "RETRY"
    def resume_after_human(self, task_id): self.resumed.append(task_id)
    def heartbeat(self, t): self.heartbeats.append(t.task_id); return t.lease_expires_at


class FakeBrowser:
    def __init__(self, result=None, error=None):
        self.result=result
        self.error=error
        self.urls=[]
        self.candidate_names=[]
        self.job_titles=[]
        self.reset_calls=0
    def fetch_resume(self, url, *, candidate_name=None, job_title=None):
        self.urls.append(url)
        self.candidate_names.append(candidate_name)
        self.job_titles.append(job_title)
        if self.error: raise self.error
        return self.result
    def reset_session(self):
        self.reset_calls += 1


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
    assert api.uploads == [("t1","ada.pdf",b"%PDF-ok","application/pdf")]
    assert browser.candidate_names == ["Ada"]
    assert browser.job_titles == ["Engineer"]
    assert api.failures == [] and api.human == []
    assert hb.started and hb.stopped
    assert worker.run_once().state == "IDLE"


def test_happy_path_uploads_docx_without_forcing_pdf(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types></Types>")
        archive.writestr("word/document.xml", "<w:document></w:document>")
    data = buffer.getvalue()

    api=FakeApi([task()])
    browser=FakeBrowser(
        BrowserResult(
            BrowserOutcome.DOWNLOADED,
            filename="ada.docx",
            data=data,
            content_type=DOCX_CONTENT_TYPE,
        )
    )
    worker=ResumeWorker(
        config=config(tmp_path),
        api=api,
        browser=browser,
        heartbeat_factory=lambda **kw: FakeHeartbeat(),
    )

    snap=worker.run_once()

    assert snap.state == "COMPLETED"
    assert api.uploads == [("t1","ada.docx",data,DOCX_CONTENT_TYPE)]
    assert api.failures == []


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


def test_candidate_level_review_does_not_block_next_candidate(tmp_path):
    second=ClaimedTask(**{**task().__dict__, "task_id":"t2", "candidate_name":"Grace"})
    api=FakeApi([task(), second])
    browser=FakeBrowser(
        BrowserResult(
            BrowserOutcome.NEEDS_HUMAN,
            human_code="INDEED_CANDIDATE_NOT_FOUND",
        )
    )
    worker=ResumeWorker(
        config=config(tmp_path),
        api=api,
        browser=browser,
        heartbeat_factory=lambda **kw: FakeHeartbeat(),
    )

    first=worker.run_once()

    assert first.state == "NEEDS_REVIEW_CONTINUE"
    assert api.human == [("t1","INDEED_CANDIDATE_NOT_FOUND")]
    assert worker.human_task_id is None
    assert len(api.claims) == 1

    browser.result=BrowserResult(
        BrowserOutcome.DOWNLOADED,
        filename="grace.pdf",
        data=b"%PDF-ok",
    )
    second_snap=worker.run_once()

    assert second_snap.state == "COMPLETED"
    assert second_snap.active_candidate == "Grace"


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
    browser=FakeBrowser(BrowserResult(BrowserOutcome.NEEDS_HUMAN, human_code="INDEED_AUTH_REQUIRED"))
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
    assert browser.reset_calls == 1


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
            human_code="INDEED_AUTH_REQUIRED",
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
    assert snap.last_error == f"INDEED_AUTH_REQUIRED — Diagnóstico local: {diagnostic}"
    assert api.human == [("t1","INDEED_AUTH_REQUIRED")]


def test_start_paused_protects_manual_login_until_explicit_resume(tmp_path):
    api=FakeApi([task()])
    browser=FakeBrowser(
        BrowserResult(BrowserOutcome.DOWNLOADED, filename="ada.pdf", data=b"%PDF-ok")
    )
    worker=ResumeWorker(
        config=config(tmp_path),
        api=api,
        browser=browser,
        heartbeat_factory=lambda **kw: FakeHeartbeat(),
        start_paused=True,
    )

    assert worker.snapshot.state == "PAUSED"
    assert worker.run_once().state == "PAUSED"
    assert len(api.claims) == 1
    assert browser.urls == []

    worker.resume()
    assert worker.run_once().state == "COMPLETED"
    assert browser.urls == ["https://indeed.test/resume"]
