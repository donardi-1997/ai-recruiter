"""Contracts for candidate-import S3, SQS, and Bedrock adapters."""

import importlib
import io
import json

import pytest


class FakeSQS:
    def __init__(self):
        self.sent = []
        self.messages = []
        self.deleted = []
        self.visibility_changes = []
        self.last_receive = None

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "m-1"}

    def receive_message(self, **kwargs):
        self.last_receive = kwargs
        return {"Messages": list(self.messages)}

    def delete_message(self, **kwargs):
        self.deleted.append(kwargs)
        return {}

    def change_message_visibility(self, **kwargs):
        self.visibility_changes.append(kwargs)
        return {}


class FakeBedrockAgent:
    def __init__(self):
        self.last_request = None
        self.status = "COMPLETE"

    def start_ingestion_job(self, **kwargs):
        self.last_request = kwargs
        return {
            "ingestionJob": {
                "ingestionJobId": "ing-1",
                "status": "STARTING",
            }
        }

    def get_ingestion_job(self, **kwargs):
        self.last_get = kwargs
        return {
            "ingestionJob": {
                "ingestionJobId": kwargs["ingestionJobId"],
                "status": self.status,
            }
        }


class FakeS3:
    def __init__(self):
        self.posts = []
        self.objects = {}
        self.puts = []
        self.deleted_keys = []

    def generate_presigned_post(self, **kwargs):
        self.posts.append(kwargs)
        return {
            "url": "https://staging.example",
            "fields": {"key": kwargs["Key"], "Content-Type": kwargs["Fields"]["Content-Type"]},
        }

    def head_object(self, *, Bucket, Key):
        obj = self.objects.get((Bucket, Key))
        if obj is None:
            raise KeyError(Key)
        return {
            "ContentLength": len(obj.get("Body", b"")),
            "ContentType": obj.get("ContentType"),
            "Metadata": obj.get("Metadata", {}),
        }

    def get_object(self, *, Bucket, Key):
        obj = self.objects[(Bucket, Key)]
        return {"Body": io.BytesIO(obj["Body"])}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
            "Body": kwargs["Body"],
            "ContentType": kwargs.get("ContentType"),
            "Metadata": kwargs.get("Metadata", {}),
        }
        return {}

    def delete_object(self, *, Bucket, Key):
        self.deleted_keys.append(Key)
        self.objects.pop((Bucket, Key), None)
        return {}

    def list_objects_v2(self, *, Bucket, Prefix):
        contents = [
            {"Key": key}
            for bucket, key in self.objects
            if bucket == Bucket and key.startswith(Prefix)
        ]
        return {"Contents": contents, "IsTruncated": False}

    def delete_objects(self, *, Bucket, Delete):
        for entry in Delete["Objects"]:
            self.delete_object(Bucket=Bucket, Key=entry["Key"])
        return {}


def _module(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        pytest.fail(f"candidate import infrastructure module is missing: {exc}")


def test_sqs_message_contains_only_schema_and_batch_id(monkeypatch):
    queue = _module("app.infrastructure.imports.queue")
    fake = FakeSQS()
    monkeypatch.setattr(queue, "_sqs_client", lambda: fake)
    monkeypatch.setattr(queue, "get_import_queue_url", lambda: "https://queue.example")

    queue.send_import_batch("batch-1")

    assert json.loads(fake.sent[0]["MessageBody"]) == {
        "schema_version": 1,
        "batch_id": "batch-1",
    }
    assert fake.sent[0]["QueueUrl"] == "https://queue.example"


def test_receive_exposes_receive_count_and_uses_long_poll(monkeypatch):
    queue = _module("app.infrastructure.imports.queue")
    fake = FakeSQS()
    fake.messages = [
        {
            "Body": '{"schema_version":1,"batch_id":"b"}',
            "ReceiptHandle": "rh",
            "Attributes": {"ApproximateReceiveCount": "5"},
        }
    ]
    monkeypatch.setattr(queue, "_sqs_client", lambda: fake)
    monkeypatch.setattr(queue, "get_import_queue_url", lambda: "https://queue.example")

    message = queue.receive_import_messages()[0]

    assert message.batch_id == "b"
    assert message.receive_count == 5
    assert message.receipt_handle == "rh"
    assert fake.last_receive["WaitTimeSeconds"] == 20
    assert "ApproximateReceiveCount" in fake.last_receive["AttributeNames"]


def test_queue_delete_and_visibility_use_receipt_handle(monkeypatch):
    queue = _module("app.infrastructure.imports.queue")
    fake = FakeSQS()
    monkeypatch.setattr(queue, "_sqs_client", lambda: fake)
    monkeypatch.setattr(queue, "get_import_queue_url", lambda: "https://queue.example")

    queue.delete_message("rh")
    queue.extend_visibility("rh", 120)

    assert fake.deleted[0]["ReceiptHandle"] == "rh"
    assert fake.visibility_changes[0]["ReceiptHandle"] == "rh"
    assert fake.visibility_changes[0]["VisibilityTimeout"] == 120


def test_bedrock_start_uses_deterministic_client_token(monkeypatch):
    ingestion = _module("app.infrastructure.imports.ingestion")
    fake = FakeBedrockAgent()
    monkeypatch.setattr(ingestion, "_client", lambda: fake)
    monkeypatch.setattr(ingestion, "KNOWLEDGE_BASE_ID", "kb-1")
    monkeypatch.setattr(ingestion, "DATA_SOURCE_ID", "ds-1")

    job_id, status = ingestion.start_batch_ingestion("batch-123")

    assert job_id == "ing-1"
    assert status == "STARTING"
    assert fake.last_request["clientToken"] == ingestion.client_token_for_batch("batch-123")
    assert fake.last_request["knowledgeBaseId"] == "kb-1"
    assert fake.last_request["dataSourceId"] == "ds-1"


def test_bedrock_status_reads_real_job(monkeypatch):
    ingestion = _module("app.infrastructure.imports.ingestion")
    fake = FakeBedrockAgent()
    monkeypatch.setattr(ingestion, "_client", lambda: fake)
    monkeypatch.setattr(ingestion, "KNOWLEDGE_BASE_ID", "kb-1")
    monkeypatch.setattr(ingestion, "DATA_SOURCE_ID", "ds-1")

    assert ingestion.get_ingestion_status("ing-1") == "COMPLETE"
    assert fake.last_get == {
        "knowledgeBaseId": "kb-1",
        "dataSourceId": "ds-1",
        "ingestionJobId": "ing-1",
    }


def test_staging_presigned_post_fixes_key_type_and_size(monkeypatch):
    storage = _module("app.infrastructure.imports.storage")
    fake = FakeS3()
    monkeypatch.setattr(storage, "_s3_client", lambda: fake)
    monkeypatch.setattr(storage, "get_import_staging_bucket", lambda: "staging-bucket")

    result = storage.create_staging_presigned_post(
        batch_id="batch-1",
        item_id="item-1",
        filename="Ana Gomez.pdf",
        content_type="application/pdf",
        size_bytes=123,
    )

    request = fake.posts[0]
    assert request["Bucket"] == "staging-bucket"
    assert request["Key"] == "imports/batch-1/item-1/Ana_Gomez.pdf"
    assert request["ExpiresIn"] == 3600
    assert {"Content-Type": "application/pdf"} in request["Conditions"]
    assert ["content-length-range", 123, 123] in request["Conditions"]
    assert result["fields"]["key"] == "imports/batch-1/item-1/Ana_Gomez.pdf"


def test_staging_read_child_write_and_cleanup(monkeypatch):
    storage = _module("app.infrastructure.imports.storage")
    fake = FakeS3()
    monkeypatch.setattr(storage, "_s3_client", lambda: fake)
    monkeypatch.setattr(storage, "get_import_staging_bucket", lambda: "staging-bucket")
    fake.objects[("staging-bucket", "imports/batch-1/item-1/a.pdf")] = {
        "Body": b"pdf",
        "ContentType": "application/pdf",
        "Metadata": {},
    }

    assert storage.head_staging_object("imports/batch-1/item-1/a.pdf")["ContentLength"] == 3
    assert storage.read_staging_object("imports/batch-1/item-1/a.pdf") == b"pdf"
    child_key = storage.write_staging_child(
        batch_id="batch-1",
        item_id="child-1",
        filename="b.docx",
        data=b"docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert child_key == "imports/batch-1/expanded/child-1/b.docx"

    storage.delete_staging_prefix("batch-1")
    assert not any(key.startswith("imports/batch-1/") for _, key in fake.objects)


def test_canonical_write_removes_stale_extension(monkeypatch):
    storage = _module("app.infrastructure.imports.storage")
    fake = FakeS3()
    monkeypatch.setattr(storage, "_s3_client", lambda: fake)
    monkeypatch.setattr(storage, "CANONICAL_BUCKET", "canonical-bucket")
    fake.objects[("canonical-bucket", "documents/cv-c1.pdf")] = {
        "Body": b"old",
        "ContentType": "application/pdf",
        "Metadata": {"document-sha256": "old"},
    }

    result = storage.write_canonical_candidate_document(
        candidate_id="c1",
        candidate_name="Ana",
        filename="ana.docx",
        data=b"docx",
        sha256="a" * 64,
    )

    assert result.changed is True
    assert result.key == "documents/cv-c1.docx"
    assert "documents/cv-c1.pdf" in fake.deleted_keys
    assert "documents/cv-c1.pdf.metadata.json" in fake.deleted_keys
    written = next(item for item in fake.puts if item["Key"] == result.key)
    assert written["Metadata"]["document-sha256"] == "a" * 64


def test_canonical_write_skips_unchanged_hash(monkeypatch):
    storage = _module("app.infrastructure.imports.storage")
    fake = FakeS3()
    monkeypatch.setattr(storage, "_s3_client", lambda: fake)
    monkeypatch.setattr(storage, "CANONICAL_BUCKET", "canonical-bucket")
    fake.objects[("canonical-bucket", "documents/cv-c1.pdf")] = {
        "Body": b"same",
        "ContentType": "application/pdf",
        "Metadata": {"document-sha256": "a" * 64},
    }

    result = storage.write_canonical_candidate_document(
        candidate_id="c1",
        candidate_name="Ana",
        filename="ana.pdf",
        data=b"same",
        sha256="a" * 64,
    )

    assert result.changed is False
    assert result.key == "documents/cv-c1.pdf"
    assert fake.puts == []
