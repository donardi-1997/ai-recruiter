"""Contracts for routing provider-neutral ingestion events through the shared SQS queue."""

import json

from app.infrastructure.imports import queue


class FakeSQS:
    def __init__(self):
        self.sent = []
        self.messages = []

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "message-1"}

    def receive_message(self, **kwargs):
        return {"Messages": list(self.messages)}


def _configure(monkeypatch, fake):
    monkeypatch.setattr(queue, "_sqs_client", lambda: fake)
    monkeypatch.setattr(queue, "get_import_queue_url", lambda: "https://queue.invalid/main")


def test_send_candidate_ingestion_uses_explicit_typed_payload(monkeypatch):
    fake = FakeSQS()
    _configure(monkeypatch, fake)

    message_id = queue.send_candidate_ingestion("event-1")

    assert message_id == "message-1"
    assert json.loads(fake.sent[0]["MessageBody"]) == {
        "schema_version": 1,
        "kind": "candidate_ingestion",
        "ingestion_event_id": "event-1",
    }


def test_receive_work_messages_deserializes_candidate_ingestion(monkeypatch):
    fake = FakeSQS()
    fake.messages = [
        {
            "Body": '{"schema_version":1,"kind":"candidate_ingestion","ingestion_event_id":"event-1"}',
            "ReceiptHandle": "receipt-c",
            "Attributes": {"ApproximateReceiveCount": "4"},
        }
    ]
    _configure(monkeypatch, fake)

    message = queue.receive_work_messages()[0]

    assert message.kind == "candidate_ingestion"
    assert message.identifier == "event-1"
    assert message.receipt_handle == "receipt-c"
    assert message.receive_count == 4
