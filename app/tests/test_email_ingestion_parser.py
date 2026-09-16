"""Contracts for normalizing Gmail messages into provider-neutral email ingestion."""

import importlib

import pytest


def _parser_module():
    try:
        return importlib.import_module("app.integrations.email_ingestion.parser")
    except ModuleNotFoundError as exc:
        pytest.fail(f"email ingestion parser is missing: {exc}")


def _message(*, sender="Indeed <alerts@indeed.com>", filename="candidate.pdf", mime_type="application/pdf"):
    return {
        "id": "gmail-1",
        "threadId": "thread-1",
        "historyId": "55",
        "internalDate": "1789574400000",
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": "New application for Country Manager Chile"},
                {"name": "Message-ID", "value": "<provider-message-1@example>"},
            ],
            "parts": [
                {
                    "mimeType": "multipart/mixed",
                    "parts": [
                        {
                            "filename": filename,
                            "mimeType": mime_type,
                            "body": {"attachmentId": "attachment-1", "size": 1234},
                        },
                        {
                            "filename": "logo.png",
                            "mimeType": "image/png",
                            "body": {"attachmentId": "attachment-logo", "size": 50},
                        },
                    ],
                }
            ],
        },
    }


def test_parser_extracts_headers_and_supported_resume_attachment_recursively():
    parser = _parser_module()

    parsed = parser.parse_gmail_message(
        _message(),
        allowed_senders=("alerts@indeed.com",),
    )

    assert parsed.message_id == "gmail-1"
    assert parsed.thread_id == "thread-1"
    assert parsed.history_id == "55"
    assert parsed.sender == "alerts@indeed.com"
    assert parsed.subject == "New application for Country Manager Chile"
    assert parsed.provider_message_id == "<provider-message-1@example>"
    assert len(parsed.attachments) == 1
    attachment = parsed.attachments[0]
    assert attachment.attachment_id == "attachment-1"
    assert attachment.filename == "candidate.pdf"
    assert attachment.content_type == "application/pdf"
    assert attachment.declared_size_bytes == 1234


def test_parser_accepts_docx_and_ignores_inline_or_unsupported_attachments():
    parser = _parser_module()

    parsed = parser.parse_gmail_message(
        _message(
            filename="candidate.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        allowed_senders=(),
    )

    assert [item.filename for item in parsed.attachments] == ["candidate.docx"]


def test_parser_rejects_sender_outside_configured_allowlist():
    parser = _parser_module()

    with pytest.raises(parser.EmailSenderNotAllowed):
        parser.parse_gmail_message(
            _message(sender="Attacker <evil@example.com>"),
            allowed_senders=("alerts@indeed.com",),
        )


def test_parser_requires_stable_gmail_message_id():
    parser = _parser_module()
    message = _message()
    message.pop("id")

    with pytest.raises(parser.InvalidEmailMessage):
        parser.parse_gmail_message(message, allowed_senders=())
