from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from types import MethodType
from urllib.parse import urlsplit

from .browser import (
    BrowserOutcome,
    BrowserResult,
    DOCX_CONTENT_TYPE,
    PDF_CONTENT_TYPE,
    normalize_resume_filename,
    validate_resume_document,
)
from .browser_use_driver import _decode_filename, _load_browser_session_class


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
    return Path(browser._config.browser_profile_dir).parent / "downloads"


def _download_snapshot(browser) -> dict[str, tuple[int, int]]:
    downloads = _download_directory(browser)
    downloads.mkdir(parents=True, exist_ok=True)
    snapshot: dict[str, tuple[int, int]] = {}
    try:
        entries = list(downloads.iterdir())
    except OSError:
        return snapshot
    for path in entries:
        try:
            if not path.is_file():
                continue
            if path.suffix.casefold() not in _SUPPORTED_RESUME_SUFFIXES:
                continue
            stat = path.stat()
            snapshot[str(path.resolve())] = (int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            continue
    return snapshot


def _completed_download_result(
    browser,
    baseline: dict[str, tuple[int, int]],
) -> BrowserResult | None:
    downloads = _download_directory(browser)
    try:
        entries = list(downloads.iterdir())
    except OSError:
        return None

    candidates: list[tuple[int, Path, tuple[int, int]]] = []
    for path in entries:
        try:
            if not path.is_file():
                continue
            if path.suffix.casefold() in _PARTIAL_DOWNLOAD_SUFFIXES:
                continue
            suffix = path.suffix.casefold()
            if suffix not in _SUPPORTED_RESUME_SUFFIXES:
                continue
            stat = path.stat()
            fingerprint = (int(stat.st_mtime_ns), int(stat.st_size))
            key = str(path.resolve())
            if baseline.get(key) == fingerprint:
                continue
            if stat.st_size <= 0 or stat.st_size > int(browser._config.max_pdf_bytes):
                continue
            candidates.append((int(stat.st_mtime_ns), path, fingerprint))
        except OSError:
            continue

    for _mtime_ns, path, _fingerprint in sorted(candidates, reverse=True):
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        suffix = path.suffix.casefold()
        declared_type = PDF_CONTENT_TYPE if suffix == ".pdf" else DOCX_CONTENT_TYPE
        try:
            canonical_type = validate_resume_document(
                payload,
                filename=path.name,
                content_type=declared_type,
                max_bytes=browser._config.max_pdf_bytes,
            )
        except Exception:
            continue

        filename = normalize_resume_filename(
            path.name,
            content_type=canonical_type,
        )
        try:
            path.unlink()
        except OSError:
            pass
        return BrowserResult(
            BrowserOutcome.DOWNLOADED,
            filename=filename,
            data=payload,
            content_type=canonical_type,
        )
    return None


def install_download_capture_compat(browser) -> None:
    """Make Indeed resume capture resilient to endpoint and CDP download changes.

    The primary path remains Chrome Network.getResponseBody. While a resume
    download is explicitly armed, this layer also accepts HTTPS Indeed attachment
    responses from alternate endpoints. As a final fallback, Browser Use is
    pointed at a private agent download directory and a newly completed PDF/DOCX
    is validated and read from disk when CDP cannot expose the response body.
    """
    if bool(getattr(browser, "_download_capture_compat_installed", False)):
        return
    browser._download_capture_compat_installed = True

    downloads = _download_directory(browser)
    downloads.mkdir(parents=True, exist_ok=True)

    original_session_class = browser._browser_session_class

    def compatible_session_factory(**kwargs):
        session_class = original_session_class or _load_browser_session_class()
        kwargs.setdefault("downloads_path", str(downloads.resolve()))
        return session_class(**kwargs)

    browser._browser_session_class = compatible_session_factory

    original_response_received = browser._on_response_received

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

    browser._on_response_received = MethodType(compatible_response_received, browser)

    original_arm_download = browser._arm_download

    def compatible_arm_download(self):
        self._download_baseline = _download_snapshot(self)
        return original_arm_download()

    browser._arm_download = MethodType(compatible_arm_download, browser)

    def compatible_download_snapshot(self):
        return _download_snapshot(self)

    browser._download_snapshot = MethodType(compatible_download_snapshot, browser)

    async def compatible_wait_for_download(
        self,
        future: asyncio.Future,
        *,
        baseline: dict[str, tuple[int, int]] | None = None,
        timeout_seconds: float | None = None,
    ) -> BrowserResult | None:
        expected_baseline = dict(
            baseline
            if baseline is not None
            else getattr(self, "_download_baseline", {})
        )
        timeout = (
            max(0.05, float(timeout_seconds))
            if timeout_seconds is not None
            else max(8.0, float(self._config.request_timeout_seconds))
        )
        deadline = time.monotonic() + timeout
        network_error: BaseException | None = None

        while True:
            if future.done():
                try:
                    return future.result()
                except asyncio.CancelledError:
                    network_error = None
                except BaseException as exc:
                    network_error = exc

            recovered = _completed_download_result(self, expected_baseline)
            if recovered is not None:
                if not future.done():
                    future.cancel()
                return recovered

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if network_error is not None:
                    raise network_error
                return None
            await asyncio.sleep(min(0.1, remaining))

    browser._wait_for_download = MethodType(compatible_wait_for_download, browser)
