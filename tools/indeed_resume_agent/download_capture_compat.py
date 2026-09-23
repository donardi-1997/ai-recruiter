from __future__ import annotations

import os
from types import MethodType
from urllib.parse import urlsplit

from .browser_use_driver import _decode_filename


_SUPPORTED_RESUME_SUFFIXES = {".pdf", ".docx"}


def _is_indeed_host(raw_url: str | None) -> bool:
    try:
        parsed = urlsplit(str(raw_url or ""))
        host = str(parsed.hostname or "").casefold()
    except Exception:
        return False
    return (
        parsed.scheme.casefold() == "https"
        and (host == "indeed.com" or host.endswith(".indeed.com"))
    )


def install_download_capture_compat(browser) -> None:
    """Capture resume attachments even when Indeed changes the download endpoint.

    The Browser Use driver already validates the resulting PDF/DOCX bytes before
    upload. This compatibility layer only broadens the network observation step:
    while a resume download is explicitly armed, a 200 attachment response from
    an HTTPS Indeed host with a PDF/DOCX filename is treated like the historical
    /api/catws/resume/v2/download response.
    """
    original = browser._on_response_received

    def compatible_response_received(self, params, session_id) -> None:
        original(params, session_id)
        try:
            response = params.get("response", {}) if hasattr(params, "get") else {}
            request_id = str(
                params.get("requestId") if hasattr(params, "get") else ""
            )
            if not request_id or request_id in self._resume_response_meta:
                return

            future = self._download_future
            if future is None or future.done():
                return
            if int(response.get("status") or 0) != 200:
                return

            url = str(response.get("url") or "")
            if not _is_indeed_host(url):
                return

            headers_raw = response.get("headers") or {}
            if not isinstance(headers_raw, dict):
                return
            headers = {
                str(key).casefold(): str(value)
                for key, value in headers_raw.items()
            }
            disposition = str(headers.get("content-disposition") or "")
            if "attachment" not in disposition.casefold():
                return

            filename = _decode_filename(disposition) or ""
            if os.path.splitext(filename)[1].casefold() not in _SUPPORTED_RESUME_SUFFIXES:
                return

            content_type = str(
                headers.get("content-type")
                or response.get("mimeType")
                or ""
            ).split(";", 1)[0].strip().casefold()
            self._resume_response_meta[request_id] = {
                "headers": headers,
                "content_type": content_type,
                "session_id": session_id,
                "url": url,
            }
        except Exception:
            return

    browser._on_response_received = MethodType(compatible_response_received, browser)
