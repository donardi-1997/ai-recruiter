"""Contracts for parsing Indeed application notification emails safely."""

import base64

import pytest


def _b64url(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _message(
    *,
    from_value: str = "Indeed <conversation-123@indeedemail.com>",
    resume_url: str = "https://profile.indeed.com/resume/candidate-123",
    include_resume_link: bool = True,
    candidate_name: str = "Wendy Dayanna Marquez Rincon",
    job_title: str = "Analista de Automatizacion e IA",
):
    link = (
        f'<a href="{resume_url}">Ver CV</a>'
        if include_resume_link
        else ""
    )
    html = (
        "<html><body>"
        f"<p><strong>{candidate_name}</strong> se postulo para "
        f"<strong>{job_title}</strong></p>"
        f"{link}"
        "</body></html>"
    )
    return {
        "id": "gmail-1",
        "threadId": "thread-1",
        "internalDate": "1789574400000",
        "payload": {
            "mimeType": "text/html",
            "headers": [
                {"name": "From", "value": from_value},
                {"name": "Subject", "value": f"{candidate_name} se postulo"},
            ],
            "body": {"data": _b64url(html)},
        },
    }


def _nested_message():
    candidate_name = "Wendy Dayanna Marquez Rincon"
    job_title = "Analista de Automatizacion e IA"
    html = (
        "<html><body>"
        f"<div>{candidate_name} se postulo para {job_title}</div>"
        '<a href="https://employers.indeed.com/resume/candidate-123">Ver CV</a>'
        "</body></html>"
    )
    return {
        "id": "gmail-1",
        "threadId": "thread-1",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "Indeed <conversation-abc@indeedemail.com>"},
                {"name": "Subject", "value": "Nueva postulacion"},
            ],
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {
                                "data": _b64url(
                                    f"{candidate_name} se postulo para {job_title}\n"
                                )
                            },
                        },
                        {
                            "mimeType": "text/html",
                            "body": {"data": _b64url(html)},
                        },
                    ],
                }
            ],
        },
    }


def _plain_text_message():
    candidate_name = "Ana Perez"
    job_title = "Country Manager Chile"
    body = (
        f"{candidate_name} se postulo para {job_title}\n"
        "Ver CV: https://www.indeed.com/resume/ana-perez\n"
    )
    return {
        "id": "gmail-plain",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "Indeed <conversation-plain@indeedemail.com>"},
                {"name": "Subject", "value": "Nueva postulacion"},
            ],
            "body": {"data": _b64url(body)},
        },
    }


def test_html_indeed_message_extracts_candidate_job_and_resume_link():
    from app.integrations.email_ingestion.indeed_email_parser import (
        parse_indeed_application_email,
    )

    parsed = parse_indeed_application_email(_message())

    assert parsed.candidate_name == "Wendy Dayanna Marquez Rincon"
    assert parsed.job_title == "Analista de Automatizacion e IA"
    assert parsed.resume_url == "https://profile.indeed.com/resume/candidate-123"
    assert parsed.sender == "conversation-123@indeedemail.com"


def test_nested_base64url_multipart_is_decoded():
    from app.integrations.email_ingestion.indeed_email_parser import (
        parse_indeed_application_email,
    )

    parsed = parse_indeed_application_email(_nested_message())

    assert parsed.message_id == "gmail-1"
    assert parsed.candidate_name == "Wendy Dayanna Marquez Rincon"
    assert parsed.job_title == "Analista de Automatizacion e IA"


def test_plain_text_fallback_extracts_application_and_resume_link():
    from app.integrations.email_ingestion.indeed_email_parser import (
        parse_indeed_application_email,
    )

    parsed = parse_indeed_application_email(_plain_text_message())

    assert parsed.candidate_name == "Ana Perez"
    assert parsed.job_title == "Country Manager Chile"
    assert parsed.resume_url == "https://www.indeed.com/resume/ana-perez"


def test_display_name_cannot_spoof_sender_domain():
    from app.integrations.email_ingestion.indeed_email_parser import (
        NotIndeedMessage,
        parse_indeed_application_email,
    )

    with pytest.raises(NotIndeedMessage):
        parse_indeed_application_email(
            _message(from_value="Indeed <attacker@example.com>")
        )


def test_external_resume_host_is_rejected():
    from app.integrations.email_ingestion.indeed_email_parser import (
        InvalidIndeedResumeLink,
        parse_indeed_application_email,
    )

    with pytest.raises(InvalidIndeedResumeLink):
        parse_indeed_application_email(
            _message(resume_url="https://indeed.com.evil.example/cv")
        )


def test_non_https_resume_link_is_rejected():
    from app.integrations.email_ingestion.indeed_email_parser import (
        InvalidIndeedResumeLink,
        parse_indeed_application_email,
    )

    with pytest.raises(InvalidIndeedResumeLink):
        parse_indeed_application_email(
            _message(resume_url="http://www.indeed.com/resume/unsafe")
        )


def test_missing_resume_link_is_invalid_but_recognized_indeed_message():
    from app.integrations.email_ingestion.indeed_email_parser import (
        InvalidIndeedMessage,
        parse_indeed_application_email,
    )

    with pytest.raises(InvalidIndeedMessage):
        parse_indeed_application_email(_message(include_resume_link=False))


def test_missing_message_id_is_invalid():
    from app.integrations.email_ingestion.indeed_email_parser import (
        InvalidIndeedMessage,
        parse_indeed_application_email,
    )

    message = _message()
    message["id"] = ""
    with pytest.raises(InvalidIndeedMessage):
        parse_indeed_application_email(message)


def test_real_indeed_boilerplate_is_removed_from_job_title():
    from app.integrations.email_ingestion.indeed_email_parser import (
        parse_indeed_application_email,
    )

    candidate_name = "CESAR ARCILA"
    body = (
        "CESAR ARCILA se postuló para el puesto de Líder de Contact Center Comercial "
        "publicado en Indeed. Encontrará su información a continuación y su CV adjunto "
        "(si se proporcionó uno).\n"
        "Ver CV: https://www.indeed.com/resume/cesar-arcila\n"
    )
    message = {
        "id": "gmail-cesar",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {
                    "name": "From",
                    "value": "Indeed <conversation-cesar@indeedemail.com>",
                },
                {"name": "Subject", "value": f"{candidate_name} se postuló"},
            ],
            "body": {"data": _b64url(body)},
        },
    }

    parsed = parse_indeed_application_email(message)

    assert parsed.candidate_name == "CESAR ARCILA"
    assert parsed.job_title == "Líder de Contact Center Comercial"


def test_extracts_external_indeed_job_id_from_job_link():
    from app.integrations.email_ingestion.indeed_email_parser import (
        parse_indeed_application_email,
    )

    candidate_name = "Ana Perez"
    job_title = "Country Manager Chile"
    html = (
        "<html><body>"
        f"<p>{candidate_name} se postulo para {job_title}</p>"
        '<a href="https://www.indeed.com/viewjob?jk=abc123XYZ987">Ver vacante</a>'
        '<a href="https://profile.indeed.com/resume/candidate-123">Ver CV</a>'
        "</body></html>"
    )
    message = {
        "id": "gmail-job-id",
        "payload": {
            "mimeType": "text/html",
            "headers": [
                {
                    "name": "From",
                    "value": "Indeed <conversation-job@indeedemail.com>",
                },
                {"name": "Subject", "value": "Nueva postulacion"},
            ],
            "body": {"data": _b64url(html)},
        },
    }

    parsed = parse_indeed_application_email(message)

    assert parsed.external_job_id == "abc123XYZ987"


def test_resume_link_without_job_identifier_keeps_external_job_id_none():
    from app.integrations.email_ingestion.indeed_email_parser import (
        parse_indeed_application_email,
    )

    parsed = parse_indeed_application_email(_message())

    assert parsed.external_job_id is None
