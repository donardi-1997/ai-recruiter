"""Provider-neutral normalization for Gmail candidate-ingestion messages."""

from __future__ import annotations

from dataclasses import dataclass
from email.utils import parseaddr
from pathlib import PurePosixPath
from typing import Any, Iterable

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
SUPPORTED_CONTENT_TYPES = {PDF_CONTENT_TYPE, DOCX_CONTENT_TYPE}
SUPPORTED_EXTENSIONS = {".pdf", ".docx"}


class InvalidEmailMessage(ValueError):
    """Raised when a Gmail payload cannot be normalized safely."""


class EmailSenderNotAllowed(PermissionError):
    """Raised when the message sender is outside the configured allowlist."""


@dataclass(frozen=True)
class NormalizedEmailAttachment:
    attachment_id: str
    filename: str
    content_type: str
    declared_size_bytes: int


@dataclass(frozen=True)
class NormalizedEmail:
    message_id: str
    thread_id: str | None
    history_id: str | None
    provider_message_id: str | None
    sender: str
    subject: str
    internal_date_ms: int | None
    attachments: tuple[NormalizedEmailAttachment, ...]


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in payload.get("headers") or []:
        name = str(item.get("name") or "").strip().casefold()
        if name and name not in result:
            result[name] = str(item.get("value") or "").strip()
    return result


def _iter_parts(part: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield part
    for child in part.get("parts") or []:
        if isinstance(child, dict):
            yield from _iter_parts(child)


def _supported_attachment(part: dict[str, Any]) -> NormalizedEmailAttachment | None:
    filename = str(part.get("filename") or "").strip()
    body = part.get("body") or {}
    attachment_id = str(body.get("attachmentId") or "").strip()
    if not filename or not attachment_id:
        return None

    extension = PurePosixPath(filename.replace("\\", "/")).suffix.casefold()
    content_type = str(part.get("mimeType") or "").strip().casefold()
    if extension not in SUPPORTED_EXTENSIONS or content_type not in SUPPORTED_CONTENT_TYPES:
        return None

    try:
        declared_size = int(body.get("size") or 0)
    except (TypeError, ValueError):
        declared_size = 0

    return NormalizedEmailAttachment(
        attachment_id=attachment_id,
        filename=filename,
        content_type=content_type,
        declared_size_bytes=max(0, declared_size),
    )


def parse_gmail_message(
    message: dict[str, Any],
    *,
    allowed_senders: tuple[str, ...] = (),
) -> NormalizedEmail:
    """Normalize one Gmail API message while excluding bodies and inline assets."""
    message_id = str(message.get("id") or "").strip()
    if not message_id:
        raise InvalidEmailMessage("GMAIL_MESSAGE_ID_MISSING")

    payload = message.get("payload") or {}
    headers = _headers(payload)
    _, sender_address = parseaddr(headers.get("from", ""))
    sender = sender_address.strip().casefold()
    if not sender:
        raise InvalidEmailMessage("EMAIL_SENDER_MISSING")

    normalized_allowlist = {
        value.strip().casefold() for value in allowed_senders if value.strip()
    }
    if normalized_allowlist and sender not in normalized_allowlist:
        raise EmailSenderNotAllowed("EMAIL_SENDER_NOT_ALLOWED")

    attachments: list[NormalizedEmailAttachment] = []
    seen_attachment_ids: set[str] = set()
    for part in _iter_parts(payload):
        attachment = _supported_attachment(part)
        if attachment is None or attachment.attachment_id in seen_attachment_ids:
            continue
        seen_attachment_ids.add(attachment.attachment_id)
        attachments.append(attachment)

    internal_date_raw = str(message.get("internalDate") or "").strip()
    try:
        internal_date_ms = int(internal_date_raw) if internal_date_raw else None
    except ValueError:
        internal_date_ms = None

    return NormalizedEmail(
        message_id=message_id,
        thread_id=str(message.get("threadId") or "").strip() or None,
        history_id=str(message.get("historyId") or "").strip() or None,
        provider_message_id=headers.get("message-id") or None,
        sender=sender,
        subject=headers.get("subject", ""),
        internal_date_ms=internal_date_ms,
        attachments=tuple(attachments),
    )
