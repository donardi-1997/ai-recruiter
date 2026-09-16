"""SQS adapter for durable candidate-import, Indeed resume, ingestion and reevaluation work."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.config import get_aws_region, get_import_queue_url
from app.infrastructure.bedrock.session import get_cached_session

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
CANDIDATE_IMPORT_KIND = "candidate_import"
INDEED_RESUME_KIND = "indeed_resume"
CANDIDATE_INGESTION_KIND = "candidate_ingestion"
JOB_REEVALUATION_KIND = "job_reevaluation"


@dataclass(frozen=True)
class ReceivedImportMessage:
    batch_id: str
    receipt_handle: str
    receive_count: int


@dataclass(frozen=True)
class ReceivedWorkMessage:
    kind: str
    identifier: str
    receipt_handle: str
    receive_count: int


def _sqs_client():
    return get_cached_session().client("sqs", region_name=get_aws_region())


def _send(payload: dict) -> str | None:
    response = _sqs_client().send_message(
        QueueUrl=get_import_queue_url(),
        MessageBody=json.dumps(payload, separators=(",", ":")),
    )
    return response.get("MessageId")


def send_import_batch(batch_id: str) -> str | None:
    """Enqueue the historical candidate-import payload unchanged."""
    return _send(
        {
            "schema_version": SCHEMA_VERSION,
            "batch_id": str(batch_id),
        }
    )


def send_indeed_resume_ingestion(resume_ingestion_id: str) -> str | None:
    """Enqueue one durable Indeed resume-processing task on the shared queue."""
    return _send(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": INDEED_RESUME_KIND,
            "resume_ingestion_id": str(resume_ingestion_id),
        }
    )


def send_candidate_ingestion(ingestion_event_id: str) -> str | None:
    """Enqueue one provider-neutral candidate-ingestion event."""
    return _send(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": CANDIDATE_INGESTION_KIND,
            "ingestion_event_id": str(ingestion_event_id),
        }
    )


def send_job_reevaluation(task_id: str) -> str | None:
    """Enqueue one durable vacancy reevaluation task on the shared queue."""
    return _send(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": JOB_REEVALUATION_KIND,
            "job_reevaluation_task_id": str(task_id),
        }
    )


def _receive_raw_messages() -> list[dict]:
    response = _sqs_client().receive_message(
        QueueUrl=get_import_queue_url(),
        MaxNumberOfMessages=10,
        WaitTimeSeconds=20,
        AttributeNames=["ApproximateReceiveCount"],
    )
    return list(response.get("Messages", []))


def _deserialize_work(raw: dict) -> ReceivedWorkMessage | None:
    try:
        body = json.loads(raw["Body"])
        if body.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported schema version")

        kind = body.get("kind") or CANDIDATE_IMPORT_KIND
        if kind == CANDIDATE_IMPORT_KIND:
            identifier = str(body["batch_id"]).strip()
        elif kind == INDEED_RESUME_KIND:
            identifier = str(body["resume_ingestion_id"]).strip()
        elif kind == CANDIDATE_INGESTION_KIND:
            identifier = str(body["ingestion_event_id"]).strip()
        elif kind == JOB_REEVALUATION_KIND:
            identifier = str(body["job_reevaluation_task_id"]).strip()
        else:
            raise ValueError("unsupported work kind")

        receipt_handle = str(raw["ReceiptHandle"])
        if not identifier:
            raise ValueError("empty work identifier")
        receive_count = int(
            raw.get("Attributes", {}).get("ApproximateReceiveCount", "1")
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring invalid shared SQS work message: %s", exc)
        return None

    return ReceivedWorkMessage(
        kind=kind,
        identifier=identifier,
        receipt_handle=receipt_handle,
        receive_count=max(receive_count, 1),
    )


def receive_work_messages() -> list[ReceivedWorkMessage]:
    """Long-poll SQS and deserialize all supported work kinds."""
    messages = []
    for raw in _receive_raw_messages():
        message = _deserialize_work(raw)
        if message is not None:
            messages.append(message)
    return messages


def receive_import_messages() -> list[ReceivedImportMessage]:
    """Preserve the historical import-only receive contract."""
    messages: list[ReceivedImportMessage] = []
    for work in receive_work_messages():
        if work.kind != CANDIDATE_IMPORT_KIND:
            continue
        messages.append(
            ReceivedImportMessage(
                batch_id=work.identifier,
                receipt_handle=work.receipt_handle,
                receive_count=work.receive_count,
            )
        )
    return messages


def delete_message(receipt_handle: str) -> None:
    _sqs_client().delete_message(
        QueueUrl=get_import_queue_url(),
        ReceiptHandle=receipt_handle,
    )


def extend_visibility(receipt_handle: str, seconds: int) -> None:
    if seconds < 0:
        raise ValueError("visibility timeout must be non-negative")
    _sqs_client().change_message_visibility(
        QueueUrl=get_import_queue_url(),
        ReceiptHandle=receipt_handle,
        VisibilityTimeout=int(seconds),
    )
