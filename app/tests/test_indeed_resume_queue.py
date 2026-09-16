"""Contracts for sharing the candidate-import SQS queue with Indeed resume work."""

import json

from app.infrastructure.imports import queue


class FakeSQS:
    def __init__(self):
        self.sent = []
        self.messages = []
        self.last_receive = None

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "message-1"}

    def receive_message(self, **kwargs):
        self.last_receive = kwargs
        return {"Messages": list(self.messages)}


def _configure(monkeypatch, fake):
    monkeypatch.setattr(queue, "_sqs_client", lambda: fake)
    monkeypatch.setattr(queue, "get_import_queue_url", lambda: "https://queue.invalid/main")


def test_send_indeed_resume_uses_explicit_typed_payload(monkeypatch):
    fake = FakeSQS()
    _configure(monkeypatch, fake)

    message_id = queue.send_indeed_resume_ingestion("resume-1")

    assert message_id == "message-1"
    assert json.loads(fake.sent[0]["MessageBody"]) == {
        "schema_version": 1,
        "kind": "indeed_resume",
        "resume_ingestion_id": "resume-1",
    }


def test_receive_work_messages_preserves_legacy_candidate_import_payload(monkeypatch):
    fake = FakeSQS()
    fake.messages = [
        {
            "Body": '{"schema_version":1,"batch_id":"batch-1"}',
            "ReceiptHandle": "receipt-1",
            "Attributes": {"ApproximateReceiveCount": "2"},
        }
    ]
    _configure(monkeypatch, fake)

    message = queue.receive_work_messages()[0]

    assert message.kind == "candidate_import"
    assert message.identifier == "batch-1"
    assert message.receipt_handle == "receipt-1"
    assert message.receive_count == 2
    assert fake.last_receive["WaitTimeSeconds"] == 20


def test_receive_work_messages_deserializes_indeed_resume(monkeypatch):
    fake = FakeSQS()
    fake.messages = [
        {
            "Body": '{"schema_version":1,"kind":"indeed_resume","resume_ingestion_id":"resume-1"}',
            "ReceiptHandle": "receipt-r",
            "Attributes": {"ApproximateReceiveCount": "5"},
        }
    ]
    _configure(monkeypatch, fake)

    message = queue.receive_work_messages()[0]

    assert message.kind == "indeed_resume"
    assert message.identifier == "resume-1"
    assert message.receipt_handle == "receipt-r"
    assert message.receive_count == 5


def test_receive_work_messages_ignores_unknown_or_malformed_payloads(monkeypatch):
    fake = FakeSQS()
    fake.messages = [
        {
            "Body": '{"schema_version":1,"kind":"mystery","resume_ingestion_id":"x"}',
            "ReceiptHandle": "bad-1",
        },
        {
            "Body": '{"schema_version":1,"kind":"indeed_resume"}',
            "ReceiptHandle": "bad-2",
        },
        {
            "Body": '{"schema_version":999,"batch_id":"old"}',
            "ReceiptHandle": "bad-3",
        },
    ]
    _configure(monkeypatch, fake)

    assert queue.receive_work_messages() == []


def test_receive_import_messages_keeps_historical_public_contract(monkeypatch):
    fake = FakeSQS()
    fake.messages = [
        {
            "Body": '{"schema_version":1,"batch_id":"batch-1"}',
            "ReceiptHandle": "receipt-1",
            "Attributes": {"ApproximateReceiveCount": "3"},
        }
    ]
    _configure(monkeypatch, fake)

    message = queue.receive_import_messages()[0]

    assert message.batch_id == "batch-1"
    assert message.receipt_handle == "receipt-1"
    assert message.receive_count == 3
