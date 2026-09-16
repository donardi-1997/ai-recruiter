"""Queue contract for durable vacancy reevaluation work."""

import json

from app.infrastructure.imports import queue


def test_send_job_reevaluation_uses_typed_payload(monkeypatch):
    payloads = []
    monkeypatch.setattr(queue, "_send", lambda payload: payloads.append(payload) or "message-1")

    assert queue.send_job_reevaluation("task-1") == "message-1"
    assert payloads == [
        {
            "schema_version": 1,
            "kind": "job_reevaluation",
            "job_reevaluation_task_id": "task-1",
        }
    ]


def test_receive_work_messages_deserializes_job_reevaluation(monkeypatch):
    raw = {
        "Body": json.dumps(
            {
                "schema_version": 1,
                "kind": "job_reevaluation",
                "job_reevaluation_task_id": "task-2",
            }
        ),
        "ReceiptHandle": "rh-2",
        "Attributes": {"ApproximateReceiveCount": "3"},
    }
    monkeypatch.setattr(queue, "_receive_raw_messages", lambda: [raw])

    messages = queue.receive_work_messages()

    assert len(messages) == 1
    assert messages[0].kind == "job_reevaluation"
    assert messages[0].identifier == "task-2"
    assert messages[0].receipt_handle == "rh-2"
    assert messages[0].receive_count == 3
