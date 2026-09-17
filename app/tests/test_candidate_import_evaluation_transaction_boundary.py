"""Regression contract for the evaluation coordinator transaction boundary."""

from types import SimpleNamespace

from app.workers import candidate_imports as worker


class _FakeDb:
    def __init__(self) -> None:
        self.transaction_open = True
        self.rollback_calls = 0
        self.commit_calls = 0

    def in_transaction(self) -> bool:
        return self.transaction_open

    def rollback(self) -> None:
        self.rollback_calls += 1
        self.transaction_open = False

    def commit(self) -> None:
        self.commit_calls += 1
        self.transaction_open = False

    def expire_all(self) -> None:
        return None


def test_evaluation_stage_releases_coordinator_transaction_before_worker_writes(monkeypatch):
    """Child evaluation sessions must not write while the coordinator holds a read tx."""
    db = _FakeDb()
    batch = SimpleNamespace(
        id="batch-1",
        status="PROCESSING",
        current_stage="EVALUATING",
        job_id="job-1",
        owner_sub="owner-1",
        evaluated_items=0,
        evaluation_failed_items=0,
    )
    state = {"evaluated": False}

    monkeypatch.setattr(worker, "_successful_candidate_ids", lambda _db, _batch: ["candidate-1"])

    def _terminal(_db, _batch, _candidate_id):
        return (state["evaluated"], False)

    monkeypatch.setattr(worker, "_terminal_evaluation_for_batch", _terminal)
    monkeypatch.setattr(worker, "get_import_evaluation_concurrency", lambda: 1)
    monkeypatch.setattr(worker.repository, "get_batch_for_worker", lambda _db, _batch_id: batch)

    def _evaluate(**_kwargs):
        assert not db.in_transaction(), (
            "coordinator transaction must be released before evaluation workers write"
        )
        state["evaluated"] = True

    monkeypatch.setattr(worker, "_evaluate_candidate_with_retries", _evaluate)

    worker._run_evaluation_stage(db, batch)

    assert db.rollback_calls == 1
    assert batch.evaluated_items == 1
    assert batch.evaluation_failed_items == 0
    assert batch.current_stage == "RANKING"
