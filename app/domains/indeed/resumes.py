"""Secure bounded download of temporary Indeed resume URLs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlsplit

import httpx

DEFAULT_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 15.0


class ResumeDownloadError(Exception):
    """Public-safe resume download failure."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class DownloadedResume:
    filename: str
    data: bytes
    sha256: str


def _safe_pdf_filename(filename: str | None) -> str:
    raw = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not raw:
        return "indeed-resume.pdf"
    stem = PurePosixPath(raw).stem.strip() or "indeed-resume"
    return f"{stem}.pdf"


def _validated_https_url(url: str) -> str:
    parsed = urlsplit(str(url or "").strip())
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ResumeDownloadError(
            "RESUME_URL_INVALID",
            "La URL temporal del CV no es valida.",
        )
    return parsed.geturl()


def download_resume(
    url: str,
    filename: str | None,
    *,
    http_client=None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> DownloadedResume:
    """Download one Indeed PDF with strict URL, redirect, size, and magic checks."""
    safe_url = _validated_https_url(url)
    bounded_max = max(1, int(max_bytes))
    owns_client = http_client is None
    client = http_client or httpx.Client(
        timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS),
        follow_redirects=False,
    )

    try:
        with client.stream(
            "GET",
            safe_url,
            follow_redirects=False,
            headers={"Accept": "application/pdf"},
        ) as response:
            if 300 <= int(response.status_code) < 400:
                raise ResumeDownloadError(
                    "RESUME_DOWNLOAD_FAILED",
                    "Indeed devolvio una redireccion inesperada para el CV.",
                )
            if int(response.status_code) != 200:
                raise ResumeDownloadError(
                    "RESUME_DOWNLOAD_FAILED",
                    "No fue posible descargar el CV desde Indeed.",
                )

            length_header = response.headers.get("content-length")
            if length_header:
                try:
                    declared = int(length_header)
                except (TypeError, ValueError):
                    declared = None
                if declared is not None and declared > bounded_max:
                    raise ResumeDownloadError(
                        "RESUME_TOO_LARGE",
                        "El CV supera el limite permitido.",
                    )

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                if not chunk:
                    continue
                total += len(chunk)
                if total > bounded_max:
                    raise ResumeDownloadError(
                        "RESUME_TOO_LARGE",
                        "El CV supera el limite permitido.",
                    )
                chunks.append(bytes(chunk))

        data = b"".join(chunks)
        if not data.startswith(b"%PDF-"):
            raise ResumeDownloadError(
                "RESUME_NOT_PDF",
                "El archivo recibido no es un PDF valido.",
            )

        return DownloadedResume(
            filename=_safe_pdf_filename(filename),
            data=data,
            sha256=hashlib.sha256(data).hexdigest(),
        )
    except ResumeDownloadError:
        raise
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise ResumeDownloadError(
            "RESUME_DOWNLOAD_FAILED",
            "No fue posible descargar el CV desde Indeed.",
        ) from exc
    finally:
        if owns_client:
            client.close()
