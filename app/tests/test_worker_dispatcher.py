"""Contracts for routing the shared SQS queue to the correct worker pipeline."""

from app.infrastructure.imports.queue import ReceivedWorkMessage
from app.workers import dispatcher


def test_dispatcher_routes_legacy_import_to_existing_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(dispatcher.candidate_imports, "handle_message", lambda message: calls.append(message))

    work = ReceivedWorkMessage(
        kind="candidate_import",
        identifier="batch-1",
        receipt_handle="rh-1",
        receive_count=2,
    )
    dispatcher.route_message(work)

    assert len(calls) == 1
    assert calls[0].batch_id == "batch-1"
    assert calls[0].receipt_handle == "rh-1"
    assert calls[0].receive_count == 2


def test_dispatcher_routes_indeed_resume_to_resume_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(dispatcher.indeed_resumes, "handle_message", lambda message: calls.append(message))

    work = ReceivedWorkMessage(
        kind="indeed_resume",
        identifier="resume-1",
        receipt_handle="rh-r",
        receive_count=1,
    )
    dispatcher.route_message(work)

    assert calls == [work]


def test_dispatcher_routes_job_reevaluation_to_worker(monkeypatch):
    calls = []
    monkeypatch.setattr(dispatcher.job_reevaluations, "handle_message", lambda message: calls.append(message))

    work = ReceivedWorkMessage(
        kind="job_reevaluation",
        identifier="task-1",
        receipt_handle="rh-j",
        receive_count=1,
    )
    dispatcher.route_message(work)

    assert calls == [work]


def test_dispatcher_repair_cycle_runs_all_durable_repair_paths(monkeypatch):
    calls = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(dispatcher, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        dispatcher.candidate_imports,
        "dispatch_undispatched_batches",
        lambda db: calls.append(("imports", db)) or 2,
    )
    monkeypatch.setattr(
        dispatcher.indeed_resumes,
        "dispatch_undispatched_resume_ingestions",
        lambda db: calls.append(("indeed", db)) or 3,
    )
    monkeypatch.setattr(
        dispatcher.candidate_ingestions,
        "dispatch_undispatched_ingestions",
        lambda db: calls.append(("ingestion", db)) or 4,
    )
    monkeypatch.setattr(
        dispatcher.job_reevaluations,
        "dispatch_undispatched_job_reevaluations",
        lambda db: calls.append(("reevaluation", db)) or 5,
    )

    assert dispatcher.repair_undispatched_work() == 14
    assert [kind for kind, _db in calls] == [
        "imports",
        "indeed",
        "ingestion",
        "reevaluation",
    ]
