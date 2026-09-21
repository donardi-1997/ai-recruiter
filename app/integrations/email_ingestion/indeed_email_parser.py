"""Safe deterministic parser for Indeed application notification emails."""

from __future__ import annotations

import base64
import binascii
import html
import re
from dataclasses import dataclass
from email.utils import parseaddr
from html.parser import HTMLParser
from typing import Any, Iterable
from urllib.parse import parse_qs, urlsplit


class NotIndeedMessage(ValueError):
    """Raised when the sender is not an allowed Indeed sender domain."""


class InvalidIndeedMessage(ValueError):
    """Raised when a recognized Indeed message is missing required fields."""


class InvalidIndeedResumeLink(ValueError):
    """Raised when a resume action points outside the allowed Indeed hosts."""


@dataclass(frozen=True)
class ParsedIndeedApplication:
    message_id: str
    thread_id: str | None
    sender: str
    subject: str
    candidate_name: str
    job_title: str
    external_job_id: str | None
    resume_url: str
    internal_date_ms: int | None


_BLOCK_TAGS = {
    "address",
    "article",
    "br",
    "div",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "p",
    "section",
    "table",
    "td",
    "th",
    "tr",
}
_RESUME_LABEL_RE = re.compile(
    r"\b(?:ver\s+cv|descargar\s+cv|ver\s+curr[ií]culum|"
    r"view\s+resume|download\s+resume)\b",
    re.IGNORECASE,
)
_APPLICATION_PATTERNS = (
    re.compile(
        r"^\s*(?P<candidate>.+?)\s+se\s+postul[oó]\s+"
        r"(?:para|a\s+la\s+vacante|al\s+empleo|a)\s+"
        r"(?P<job>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?P<candidate>.+?)\s+aplic[oó]\s+"
        r"(?:para|a)\s+(?P<job>.+?)\s*$",
        re.IGNORECASE,
    ),
)


def _normalize_space(value: str) -> str:
    return " ".join(str(value or "").split())


def _clean_job_title(value: str) -> str:
    title = _normalize_space(value)
    title = re.sub(
        r"^(?:el\s+puesto\s+de|puesto\s+de|la\s+vacante\s+de|vacante\s+de)\s+",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(
        r"\s+publicad[oa]\s+en\s+Indeed\b.*$",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(
        r"\.\s+Encontrar[aá]\s+su\s+informaci[oó]n\b.*$",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return _normalize_space(title).strip(" .-")


def _host_allowed(host: str, suffixes: tuple[str, ...]) -> bool:
    normalized = host.strip().casefold().rstrip(".")
    for raw_suffix in suffixes:
        suffix = raw_suffix.strip().casefold().lstrip(".")
        if suffix and (normalized == suffix or normalized.endswith("." + suffix)):
            return True
    return False


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in payload.get("headers") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().casefold()
        if name and name not in result:
            result[name] = str(item.get("value") or "").strip()
    return result


def _iter_parts(part: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield part
    for child in part.get("parts") or []:
        if isinstance(child, dict):
            yield from _iter_parts(child)


def _decode_body_data(part: dict[str, Any]) -> str | None:
    body = part.get("body") or {}
    encoded = str(body.get("data") or "").strip()
    if not encoded:
        return None
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        return raw.decode("utf-8", errors="replace")
    except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
        raise InvalidIndeedMessage("INDEED_EMAIL_BODY_INVALID") from exc


class _IndeedHtmlExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._text: list[str] = []
        self._active_anchor_href: str | None = None
        self._active_anchor_text: list[str] = []
        self.anchors: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in _BLOCK_TAGS:
            self._text.append("\n")
        if normalized_tag == "a":
            href = next(
                (value for name, value in attrs if name.casefold() == "href" and value),
                None,
            )
            self._active_anchor_href = href
            self._active_anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag == "a" and self._active_anchor_href:
            label = _normalize_space(" ".join(self._active_anchor_text))
            self.anchors.append((self._active_anchor_href, label))
            self._active_anchor_href = None
            self._active_anchor_text = []
        if normalized_tag in _BLOCK_TAGS:
            self._text.append("\n")

    def handle_data(self, data: str) -> None:
        if not data:
            return
        self._text.append(data)
        self._text.append(" ")
        if self._active_anchor_href is not None:
            self._active_anchor_text.append(data)

    @property
    def visible_text(self) -> str:
        lines = [
            _normalize_space(line)
            for line in "".join(self._text).splitlines()
        ]
        return "\n".join(line for line in lines if line)


def _extract_html(raw_html: str) -> tuple[str, list[tuple[str, str]]]:
    parser = _IndeedHtmlExtractor()
    try:
        parser.feed(raw_html)
        parser.close()
    except Exception as exc:  # HTMLParser can surface malformed entity edge cases.
        raise InvalidIndeedMessage("INDEED_EMAIL_HTML_INVALID") from exc
    return parser.visible_text, parser.anchors


def _extract_application_fields(texts: Iterable[str]) -> tuple[str, str]:
    for text in texts:
        for raw_line in str(text or "").splitlines():
            line = _normalize_space(raw_line)
            if not line:
                continue
            for pattern in _APPLICATION_PATTERNS:
                match = pattern.match(line)
                if not match:
                    continue
                candidate_name = _normalize_space(match.group("candidate"))
                job_title = _clean_job_title(match.group("job"))
                if candidate_name and job_title:
                    return candidate_name, job_title
    raise InvalidIndeedMessage("INDEED_APPLICATION_FIELDS_MISSING")


def _validate_resume_url(
    value: str,
    *,
    resume_host_suffixes: tuple[str, ...],
) -> str:
    url = html.unescape(str(value or "").strip())
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.scheme.casefold() != "https" or not host:
        raise InvalidIndeedResumeLink("INDEED_RESUME_LINK_INVALID")
    if not _host_allowed(host, resume_host_suffixes):
        raise InvalidIndeedResumeLink("INDEED_RESUME_LINK_INVALID")
    return url




_JOB_ID_QUERY_KEYS = (
    "sourcedpostingid",
    "jobkey",
    "jobid",
    "vjk",
    "jk",
)


def _extract_external_job_id(
    anchors: Iterable[tuple[str, str]],
    *,
    host_suffixes: tuple[str, ...],
) -> str | None:
    """Extract a stable Indeed posting identifier when the email exposes one."""
    for href, _label in anchors:
        raw = html.unescape(str(href or "").strip())
        if not raw:
            continue
        try:
            parsed = urlsplit(raw)
        except ValueError:
            continue
        host = parsed.hostname or ""
        if parsed.scheme.casefold() != "https" or not _host_allowed(host, host_suffixes):
            continue
        query = {
            str(key).casefold(): values
            for key, values in parse_qs(parsed.query, keep_blank_values=False).items()
        }
        for key in _JOB_ID_QUERY_KEYS:
            values = query.get(key)
            if not values:
                continue
            value = str(values[0] or "").strip()
            if re.fullmatch(r"[A-Za-z0-9_-]{4,200}", value):
                return value
    return None


def _resume_link_from_html(
    anchors: Iterable[tuple[str, str]],
    *,
    resume_host_suffixes: tuple[str, ...],
) -> str | None:
    for href, label in anchors:
        if _RESUME_LABEL_RE.search(_normalize_space(label)):
            return _validate_resume_url(
                href,
                resume_host_suffixes=resume_host_suffixes,
            )
    return None


def _resume_link_from_plain_text(
    texts: Iterable[str],
    *,
    resume_host_suffixes: tuple[str, ...],
) -> str | None:
    url_pattern = re.compile(
        r"(?:ver\s+cv|descargar\s+cv|view\s+resume|download\s+resume)"
        r"\s*:?\s*(https?://[^\s<>\"']+)",
        re.IGNORECASE,
    )
    for text in texts:
        match = url_pattern.search(str(text or ""))
        if match:
            return _validate_resume_url(
                match.group(1).rstrip(".,);]"),
                resume_host_suffixes=resume_host_suffixes,
            )
    return None


def parse_indeed_application_email(
    message: dict[str, Any],
    *,
    sender_domains: tuple[str, ...] = ("indeedemail.com",),
    resume_host_suffixes: tuple[str, ...] = ("indeed.com", "indeedemail.com"),
) -> ParsedIndeedApplication:
    """Parse one Gmail API message as a trusted Indeed application notification."""
    message_id = str(message.get("id") or "").strip()
    if not message_id:
        raise InvalidIndeedMessage("GMAIL_MESSAGE_ID_MISSING")

    payload = message.get("payload") or {}
    headers = _headers(payload)
    _, sender_address = parseaddr(headers.get("from", ""))
    sender = sender_address.strip().casefold()
    sender_domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
    if not sender_domain or not _host_allowed(sender_domain, sender_domains):
        raise NotIndeedMessage("EMAIL_SENDER_NOT_INDEED")

    plain_texts: list[str] = []
    html_texts: list[str] = []
    anchors: list[tuple[str, str]] = []
    for part in _iter_parts(payload):
        mime_type = str(part.get("mimeType") or "").strip().casefold()
        if mime_type not in {"text/plain", "text/html"}:
            continue
        decoded = _decode_body_data(part)
        if decoded is None:
            continue
        if mime_type == "text/plain":
            plain_texts.append(decoded)
        else:
            visible_text, part_anchors = _extract_html(decoded)
            html_texts.append(visible_text)
            anchors.extend(part_anchors)

    resume_url = _resume_link_from_html(
        anchors,
        resume_host_suffixes=resume_host_suffixes,
    )
    if resume_url is None:
        resume_url = _resume_link_from_plain_text(
            plain_texts,
            resume_host_suffixes=resume_host_suffixes,
        )
    if resume_url is None:
        raise InvalidIndeedMessage("INDEED_RESUME_LINK_MISSING")

    candidate_name, job_title = _extract_application_fields(
        (*html_texts, *plain_texts)
    )
    external_job_id = _extract_external_job_id(
        anchors,
        host_suffixes=resume_host_suffixes,
    )

    internal_date_raw = str(message.get("internalDate") or "").strip()
    try:
        internal_date_ms = int(internal_date_raw) if internal_date_raw else None
    except ValueError:
        internal_date_ms = None

    return ParsedIndeedApplication(
        message_id=message_id,
        thread_id=str(message.get("threadId") or "").strip() or None,
        sender=sender,
        subject=headers.get("subject", ""),
        candidate_name=candidate_name,
        job_title=job_title,
        external_job_id=external_job_id,
        resume_url=resume_url,
        internal_date_ms=internal_date_ms,
    )
