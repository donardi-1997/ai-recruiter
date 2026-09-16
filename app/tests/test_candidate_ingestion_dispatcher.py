"""Contracts for dispatching provider-neutral candidate ingestion work."""

from app.infrastructure.imports.queue import ReceivedWorkMessage
from app.workers import dispatcher


def test_dispatcher_routes_candidate_ingestion_to_neutral_worker(monkeypatch):
    calls = []
    monkeypatch.setattr(
        dispatcher.candidate_ingestions,
        "handle_message",
        lambda message: calls.append(message),
    )

    work = ReceivedWorkMessage(
        kind="candidate_ingestion",
        identifier="event-1",
        receipt_handle="rh-c",
        receive_count=1,
    )
    dispatcher.route_message(work)

    assert calls == [work]


def test_dispatcher_repair_cycle_includes_candidate_ingestion(monkeypatch):
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
    # This test protects the candidate-ingestion repair path specifically.
    # The shared-dispatcher suite separately covers the reevaluation repair path.
    monkeypatch.setattr(
        dispatcher.job_reevaluations,
        "dispatch_undispatched_job_reevaluations",
        lambda _db: 0,
    )

    assert dispatcher.repair_undispatched_work() == 9
    assert [kind for kind, _db in calls] == ["imports", "indeed", "ingestion"]
