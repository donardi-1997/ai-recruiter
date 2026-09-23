from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import MethodType
from urllib.parse import urlsplit

from .browser import (
    BrowserOutcome,
    BrowserResult,
    normalize_resume_filename,
    validate_resume_document,
)
from .browser_use_driver import _decode_filename


_SUPPORTED_RESUME_SUFFIXES = {".pdf", ".docx"}
_PARTIAL_DOWNLOAD_SUFFIXES = {".crdownload", ".part", ".tmp"}


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


def _download_directory(browser) -> Path:
    session = getattr(browser, "_browser", None)
    holders = (
        session,
        getattr(session, "browser_profile", None),
        getattr(session, "profile", None),
    )
    for holder in holders:
        if holder is None:
            continue
        raw = getattr(holder, "downloads_path", None)
        if raw:
            return Path(raw)

    # Browser Use is not started in unit tests and older releases did not expose
    # downloads_path consistently. Keep a deterministic agent-local fallback.
    return Path(browser._config.browser_profile_dir).parent / "downloads"


def _download_snapshot(browser) -> dict[str, tuple[int, int]]:
    directory = _download_directory(browser)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {}

    snapshot: dict[str, tuple[int, int]] = {}
    try:
        entries = list(directory.iterdir())
    except OSError:
        return snapshot

    for path in entries:
        try:
            if not path.is_file():
                continue
            suffix = path.suffix.casefold()
            if suffix in _PARTIAL_DOWNLOAD_SUFFIXES:
                continue
            if suffix not in _SUPPORTED_RESUME_SUFFIXES:
                continue
            stat = path.stat()
            snapshot[path.name] = (int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            continue
    return snapshot


def _completed_download_since(
    browser,
    baseline: dict[str, tuple[int, int]] | None,
) -> BrowserResult | None:
    directory = _download_directory(browser)
    before = dict(baseline or {})
    current = _download_snapshot(browser)
    changed = [
        (name, metadata)
        for name, metadata in current.items()
        if before.get(name) != metadata
    ]
    changed.sort(key=lambda item: item[1][0], reverse=True)

    for name, _metadata in changed:
        path = directory / name
        try:
            payload = path.read_bytes()
            canonical_type = validate_resume_document(
                payload,
                filename=name,
                content_type=None,
                max_bytes=browser._config.max_pdf_bytes,
            )
        except (OSError, ValueError):
            # A final-name file can briefly be visible while antivirus/indexing
            # still has it in flux. Keep polling rather than treating it as a CV.
            continue

        return BrowserResult(
            BrowserOutcome.DOWNLOADED,
            filename=normalize_resume_filename(name, content_type=canonical_type),
            data=payload,
            content_type=canonical_type,
        )
    return None


def install_download_capture_compat(browser) -> None:
    """Recover Indeed resume downloads from network or Chrome's completed file.

    Network capture remains the primary path. The filesystem path is a bounded
    fallback for cases where Chrome completes a PDF/DOCX download but CDP cannot
    return Network.getResponseBody. Partial files such as ``.crdownload`` are
    never accepted, and recovered bytes pass the same resume validator used by
    network capture before they are returned to the worker.
    """
    original_response_received = browser._on_response_received
    original_arm_download = browser._arm_download

    def compatible_response_received(self, params, session_id) -> None:
        original_response_received(params, session_id)
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

    def compatible_download_snapshot(self) -> dict[str, tuple[int, int]]:
        return _download_snapshot(self)

    def compatible_arm_download(self):
        self._download_file_baseline = _download_snapshot(self)
        return original_arm_download()

    async def compatible_wait_for_download(
        self,
        future,
        *,
        baseline: dict[str, tuple[int, int]] | None = None,
        timeout_seconds: float | None = None,
    ) -> BrowserResult | None:
        resolved_baseline = (
            dict(baseline)
            if baseline is not None
            else dict(getattr(self, "_download_file_baseline", {}) or {})
        )
        timeout = (
            max(0.0, float(timeout_seconds))
            if timeout_seconds is not None
            else max(8.0, float(self._config.request_timeout_seconds))
        )
        deadline = asyncio.get_running_loop().time() + timeout

        while True:
            if future.done():
                return future.result()

            recovered = _completed_download_since(self, resolved_baseline)
            if recovered is not None:
                if not future.done():
                    future.set_result(recovered)
                return recovered

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(0.05, remaining))

    browser._on_response_received = MethodType(compatible_response_received, browser)
    browser._download_snapshot = MethodType(compatible_download_snapshot, browser)
    browser._arm_download = MethodType(compatible_arm_download, browser)
    browser._wait_for_download = MethodType(compatible_wait_for_download, browser)
