"""Security and storage contracts for Indeed resume downloads."""

import hashlib
import importlib

import pytest

from app.infrastructure.imports import storage


class FakeResponse:
    def __init__(self, *, status_code=200, headers=None, chunks=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks or [])

    def iter_bytes(self):
        yield from self._chunks


class FakeStreamContext:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self.response

    def __exit__(self, exc_type, exc, tb):
        return False


def public_resolver(host, port, type=None):
    return [(2, 1, 6, "", ("93.184.216.34", port))]


class FakeHTTP:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def stream(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeStreamContext(self.response)


def _resumes():
    try:
        return importlib.import_module("app.domains.indeed.resumes")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Indeed resume downloader is missing: {exc}")


def test_download_rejects_non_https_before_network_call():
    resumes = _resumes()
    fake = FakeHTTP(FakeResponse(chunks=[b"%PDF-ok"]))

    with pytest.raises(resumes.ResumeDownloadError) as exc:
        resumes.download_resume("http://example.invalid/cv.pdf", "cv.pdf", http_client=fake, host_resolver=public_resolver)

    assert exc.value.code == "RESUME_URL_INVALID"
    assert fake.calls == []


def test_download_rejects_local_and_private_destinations_before_network_call():
    resumes = _resumes()
    fake = FakeHTTP(FakeResponse(chunks=[b"%PDF-ok"]))

    with pytest.raises(resumes.ResumeDownloadError):
        resumes.download_resume(
            "https://127.0.0.1/cv.pdf",
            "cv.pdf",
            http_client=fake,
            host_resolver=public_resolver,
        )
    with pytest.raises(resumes.ResumeDownloadError):
        resumes.download_resume(
            "https://metadata.internal/cv.pdf",
            "cv.pdf",
            http_client=fake,
            host_resolver=lambda *args, **kwargs: [
                (2, 1, 6, "", ("169.254.169.254", 443))
            ],
        )

    assert fake.calls == []


def test_download_rejects_embedded_credentials_and_nonstandard_ports():
    resumes = _resumes()
    fake = FakeHTTP(FakeResponse(chunks=[b"%PDF-ok"]))

    for url in (
        "https://user:secret@example.com/cv.pdf",
        "https://example.com:8443/cv.pdf",
    ):
        with pytest.raises(resumes.ResumeDownloadError) as exc:
            resumes.download_resume(
                url,
                "cv.pdf",
                http_client=fake,
                host_resolver=public_resolver,
            )
        assert exc.value.code == "RESUME_URL_INVALID"

    assert fake.calls == []


def test_download_rejects_redirect_without_following_location():
    resumes = _resumes()
    fake = FakeHTTP(
        FakeResponse(
            status_code=302,
            headers={"location": "https://other.invalid/cv.pdf"},
        )
    )

    with pytest.raises(resumes.ResumeDownloadError) as exc:
        resumes.download_resume("https://s3.invalid/cv.pdf?secret=x", "cv.pdf", http_client=fake, host_resolver=public_resolver)

    assert exc.value.code == "RESUME_DOWNLOAD_FAILED"
    assert fake.calls[0][2]["follow_redirects"] is False


def test_download_rejects_content_length_above_limit():
    resumes = _resumes()
    fake = FakeHTTP(
        FakeResponse(
            headers={"content-length": str(101)},
            chunks=[b"%PDF-"],
        )
    )

    with pytest.raises(resumes.ResumeDownloadError) as exc:
        resumes.download_resume(
            "https://s3.invalid/cv.pdf",
            "cv.pdf",
            http_client=fake,
            max_bytes=100,
            host_resolver=public_resolver,
        )

    assert exc.value.code == "RESUME_TOO_LARGE"


def test_download_rejects_stream_that_crosses_limit_without_content_length():
    resumes = _resumes()
    fake = FakeHTTP(FakeResponse(chunks=[b"%PDF-", b"x" * 96]))

    with pytest.raises(resumes.ResumeDownloadError) as exc:
        resumes.download_resume(
            "https://s3.invalid/cv.pdf",
            "cv.pdf",
            http_client=fake,
            max_bytes=100,
            host_resolver=public_resolver,
        )

    assert exc.value.code == "RESUME_TOO_LARGE"


def test_download_rejects_non_pdf_magic_and_never_leaks_query_in_error():
    resumes = _resumes()
    fake = FakeHTTP(FakeResponse(chunks=[b"not a pdf"]))
    secret_url = "https://s3.invalid/cv.pdf?X-Amz-Signature=super-secret"

    with pytest.raises(resumes.ResumeDownloadError) as exc:
        resumes.download_resume(secret_url, "cv.pdf", http_client=fake, host_resolver=public_resolver)

    assert exc.value.code == "RESUME_NOT_PDF"
    assert "super-secret" not in str(exc.value)


def test_download_returns_normalized_pdf_name_bytes_and_sha256():
    resumes = _resumes()
    data = b"%PDF-1.7\nhello"
    fake = FakeHTTP(FakeResponse(headers={"content-length": str(len(data))}, chunks=[data]))

    result = resumes.download_resume(
        "https://s3.invalid/cv.pdf?sig=fake",
        "Ana Perez final.docx",
        http_client=fake,
        host_resolver=public_resolver,
    )

    assert result.filename == "Ana Perez final.pdf"
    assert result.data == data
    assert result.sha256 == hashlib.sha256(data).hexdigest()
    assert fake.calls[0][0] == "GET"
    assert fake.calls[0][2]["follow_redirects"] is False


def test_canonical_download_generates_short_lived_presigned_get(monkeypatch):
    class FakeS3:
        def __init__(self):
            self.calls = []

        def head_object(self, *, Bucket, Key):
            if Key.endswith(".pdf"):
                return {"ContentLength": 10, "Metadata": {}}
            raise KeyError(Key)

        def generate_presigned_url(self, operation, Params, ExpiresIn):
            self.calls.append((operation, Params, ExpiresIn))
            return "https://canonical.invalid/download"

    fake = FakeS3()
    monkeypatch.setattr(storage, "_s3_client", lambda: fake)
    monkeypatch.setattr(storage, "CANONICAL_BUCKET", "canonical")

    result = storage.create_canonical_candidate_download("candidate-1", expires_in=300)

    assert result == {
        "url": "https://canonical.invalid/download",
        "expires_in": 300,
        "key": "documents/cv-candidate-1.pdf",
    }
    operation, params, expires = fake.calls[0]
    assert operation == "get_object"
    assert params == {"Bucket": "canonical", "Key": "documents/cv-candidate-1.pdf"}
    assert expires == 300
