from tools.indeed_resume_agent.worker import WorkerSnapshot


def test_waiting_snapshot_shape_documents_required_context():
    snapshot = WorkerSnapshot(
        state="WAITING_FOR_HUMAN",
        active_candidate="Ada",
        processed_session=0,
        last_error="INDEED_AUTH_REQUIRED",
    )
    assert snapshot.active_candidate == "Ada"
    assert snapshot.last_error == "INDEED_AUTH_REQUIRED"
