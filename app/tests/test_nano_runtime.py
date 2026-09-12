"""Regression contracts for the low-memory Nano runtime profile."""

import inspect
import io
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[2]


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


def test_worker_archive_path_is_file_backed_and_incremental():
    from app.workers import candidate_imports

    source = inspect.getsource(candidate_imports._expand_archives_once)

    assert "SpooledTemporaryFile" in source
    assert "download_staging_object_to_file" in source
    assert "iter_zip_documents" in source
    assert "read_staging_object" not in source
    assert "documents.expand_zip" not in source


def test_production_deploy_uses_nano_runtime_limits():
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    db_source = (ROOT / "app/db.py").read_text(encoding="utf-8")
    api_script = (ROOT / "scripts/deploy-api.sh").read_text(encoding="utf-8")

    assert 'IMPORT_EVALUATION_CONCURRENCY="1"' in workflow
    assert 'os.getenv("PG_POOL_SIZE", "2")' in db_source
    assert 'os.getenv("PG_MAX_OVERFLOW", "2")' in db_source
    assert 'PG_POOL_SIZE="${PG_POOL_SIZE:-2}"' in api_script
    assert 'PG_MAX_OVERFLOW="${PG_MAX_OVERFLOW:-2}"' in api_script
    assert '-e "PG_POOL_SIZE=$PG_POOL_SIZE"' in api_script
    assert '-e "PG_MAX_OVERFLOW=$PG_MAX_OVERFLOW"' in api_script


def test_nano_host_script_configures_swap_logs_and_postgres():
    script = (ROOT / "scripts/configure-nano-host.sh").read_text(encoding="utf-8")

    assert "2G" in script
    assert "mkswap" in script
    assert "swapon" in script
    assert "vm.swappiness=10" in script
    assert '"max-size": "10m"' in script
    assert '"max-file": "3"' in script
    assert "shared_buffers" in script and "64MB" in script
    assert "work_mem" in script and "2MB" in script
    assert "maintenance_work_mem" in script and "32MB" in script
    assert "effective_cache_size" in script and "192MB" in script
    assert "max_connections" in script and "20" in script


def test_deploy_prunes_dangling_images_after_runtime_verification():
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    verification = workflow.index("DEPLOYMENT_FRONTEND_OK")
    prune = workflow.index("docker image prune -f")
    assert prune > verification
