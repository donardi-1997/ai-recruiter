from datetime import datetime, timezone
from types import SimpleNamespace

from tools.indeed_resume_agent.api_client import ClaimedTask
from tools.indeed_resume_agent.browser import BrowserOutcome, BrowserResult
from tools.indeed_resume_agent.worker import ResumeWorker


class FakeApi:
    def __init__(self, task):
        self.task = task
        self.human = []

    def claim(self):
        task, self.task = self.task, None
        return task

    def needs_human(self, task, *, code):
        self.human.append((task.task_id, code))

    def heartbeat(self, task):
        return task.lease_expires_at


class FakeBrowser:
    def fetch_resume(self, url, *, candidate_name=None, job_title=None):
        return BrowserResult(
            BrowserOutcome.NEEDS_HUMAN,
            human_code="INDEED_AUTH_REQUIRED",
        )


class FakeHeartbeat:
    error = None

    def start(self):
        pass

    def stop(self):
        pass


def test_waiting_for_human_preserves_reason_and_candidate_across_ticks():
    task = ClaimedTask(
        task_id="t1",
        candidate_name="Ada",
        job_title="Engineer",
        resume_url="resume",
        lease_token="lease",
        lease_expires_at=datetime(2026, 9, 23, 21, 0, tzinfo=timezone.utc),
    )
    worker = ResumeWorker(
        config=SimpleNamespace(heartbeat_interval_seconds=10),
        api=FakeApi(task),
        browser=FakeBrowser(),
        heartbeat_factory=lambda **kwargs: FakeHeartbeat(),
    )

    first = worker.run_once()
    second = worker.run_once()

    assert first.state == "WAITING_FOR_HUMAN"
    assert first.active_candidate == "Ada"
    assert first.last_error == "INDEED_AUTH_REQUIRED"
    assert second.state == "WAITING_FOR_HUMAN"
    assert second.active_candidate == "Ada"
    assert second.last_error == "INDEED_AUTH_REQUIRED"
