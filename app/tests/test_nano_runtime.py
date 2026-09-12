"""Regression contracts for the low-memory Nano runtime profile."""

import inspect
import io
import zipfile


class RecordingBody:
    def __init__(self, payload: bytes):
        self._stream = io.BytesIO(payload)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self._stream.read(size)


class StreamingFakeS3:
    def __init__(self, payload: bytes):
        self.body = RecordingBody(payload)

    def get_object(self, *, Bucket, Key):
        assert Bucket == "staging-bucket"
        assert Key == "imports/batch/archive.zip"
        return {"Body": self.body}


def _zip_file(entries: dict[str, bytes]) -> io.BytesIO:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    stream.seek(0)
    return stream


def test_staging_download_streams_in_bounded_chunks_and_rewinds(monkeypatch):
    from app.infrastructure.imports import storage

    payload = (b"candidate-data-" * 200_000) + b"end"
    fake = StreamingFakeS3(payload)
    monkeypatch.setattr(storage, "_s3_client", lambda: fake)
    monkeypatch.setattr(storage, "get_import_staging_bucket", lambda: "staging-bucket")

    target = io.BytesIO()
    written = storage.download_staging_object_to_file(
        "imports/batch/archive.zip",
        target,
    )

    assert written == len(payload)
    assert target.tell() == 0
    assert target.read() == payload
    assert len(fake.body.read_sizes) > 2
    assert set(fake.body.read_sizes[:-1]) == {storage.STREAM_CHUNK_BYTES}
    assert fake.body.read_sizes[-1] == storage.STREAM_CHUNK_BYTES


def test_zip_documents_are_exposed_as_incremental_generator():
    from app.infrastructure.imports import documents

    archive = _zip_file(
        {
            "first.pdf": b"first-pdf",
            "second.docx": b"second-docx",
        }
    )

    expanded = documents.iter_zip_documents(
        archive,
        remaining_documents=500,
        remaining_bytes=1024 * 1024 * 1024,
    )

    assert inspect.isgenerator(expanded)
    first = next(expanded)
    assert first.filename == "first.pdf"
    assert first.data == b"first-pdf"
    second = next(expanded)
    assert second.filename == "second.docx"
    assert second.data == b"second-docx"
    try:
        next(expanded)
    except StopIteration:
        pass
    else:
        raise AssertionError("archive iterator yielded more than two documents")
