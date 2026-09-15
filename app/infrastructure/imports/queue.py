"""SQS adapter for durable candidate-import batch delivery."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.config import get_aws_region, get_import_queue_url
from app.infrastructure.bedrock.session import get_cached_session

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ReceivedImportMessage:
    batch_id: str
    receipt_handle: str
    receive_count: int


def _sqs_client():
    return get_cached_session().client("sqs", region_name=get_aws_region())


def send_import_batch(batch_id: str) -> str | None:
    """Enqueue only the stable schema version and batch identifier."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "batch_id": str(batch_id),
    }
    response = _sqs_client().send_message(
        QueueUrl=get_import_queue_url(),
        MessageBody=json.dumps(payload, separators=(",", ":")),
    )
    return response.get("MessageId")


def receive_import_messages() -> list[ReceivedImportMessage]:
    """Long-poll SQS and deserialize supported import messages."""
    response = _sqs_client().receive_message(
        QueueUrl=get_import_queue_url(),
        MaxNumberOfMessages=10,
        WaitTimeSeconds=20,
        AttributeNames=["ApproximateReceiveCount"],
    )

    messages: list[ReceivedImportMessage] = []
    for raw in response.get("Messages", []):
        try:
            body = json.loads(raw["Body"])
            if body.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("unsupported schema version")
            batch_id = str(body["batch_id"]).strip()
            receipt_handle = str(raw["ReceiptHandle"])
            if not batch_id:
                raise ValueError("empty batch id")
            receive_count = int(
                raw.get("Attributes", {}).get("ApproximateReceiveCount", "1")
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring invalid candidate-import SQS message: %s", exc)
            continue

        messages.append(
            ReceivedImportMessage(
                batch_id=batch_id,
                receipt_handle=receipt_handle,
                receive_count=max(receive_count, 1),
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
