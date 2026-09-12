"""Regression contracts for the low-memory Nano runtime profile."""

import io


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
