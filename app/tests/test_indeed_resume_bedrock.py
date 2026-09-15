"""Bedrock ingestion contracts shared by import batches and Indeed resumes."""

import hashlib

from app.infrastructure.imports import ingestion


class FakeBedrockAgent:
    def __init__(self):
        self.last_request = None

    def start_ingestion_job(self, **kwargs):
        self.last_request = kwargs
        return {
            "ingestionJob": {
                "ingestionJobId": "ing-indeed-1",
                "status": "STARTING",
            }
        }


def test_indeed_resume_ingestion_uses_deterministic_operation_token(monkeypatch):
    fake = FakeBedrockAgent()
    monkeypatch.setattr(ingestion, "_client", lambda: fake)
    monkeypatch.setattr(ingestion, "KNOWLEDGE_BASE_ID", "kb-1")
    monkeypatch.setattr(ingestion, "DATA_SOURCE_ID", "ds-1")
    sha = "a" * 64

    job_id, status = ingestion.start_indeed_resume_ingestion("resume-1", sha)

    operation_key = f"indeed-resume:resume-1:{sha}"
    assert job_id == "ing-indeed-1"
    assert status == "STARTING"
    assert fake.last_request["clientToken"] == hashlib.sha256(operation_key.encode("utf-8")).hexdigest()
    assert fake.last_request["description"].startswith("indeed-resume:resume-1")


def test_candidate_import_ingestion_token_contract_is_unchanged(monkeypatch):
    fake = FakeBedrockAgent()
    monkeypatch.setattr(ingestion, "_client", lambda: fake)
    monkeypatch.setattr(ingestion, "KNOWLEDGE_BASE_ID", "kb-1")
    monkeypatch.setattr(ingestion, "DATA_SOURCE_ID", "ds-1")

    ingestion.start_batch_ingestion("batch-123")

    assert fake.last_request["clientToken"] == ingestion.client_token_for_batch("batch-123")
    assert fake.last_request["description"] == "candidate-import:batch-123"
