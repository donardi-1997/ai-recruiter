"""S3 adapters for candidate-import staging and canonical candidate documents."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from botocore.exceptions import ClientError

from app.config import get_aws_region, get_import_staging_bucket
from app.infrastructure.bedrock.session import get_cached_session

CANONICAL_BUCKET = os.getenv("S3_BUCKET", "ai-cv-rag-adrian-2026")
CANONICAL_PREFIX = "documents"
PRESIGNED_POST_EXPIRY_SECONDS = 3600
STREAM_CHUNK_BYTES = 1024 * 1024

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


@dataclass(frozen=True)
class CanonicalWriteResult:
    key: str
    changed: bool


def _s3_client():
    return get_cached_session().client("s3", region_name=get_aws_region())


def _safe_filename(filename: str) -> str:
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", basename).strip("._")
    return safe or "upload"


def _document_extension(filename: str) -> str:
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.casefold()
    if suffix not in {".pdf", ".docx"}:
        raise ValueError("canonical candidate documents must be PDF or DOCX")
    return suffix


def _content_type_for_extension(extension: str) -> str:
    if extension == ".pdf":
        return PDF_CONTENT_TYPE
    if extension == ".docx":
        return DOCX_CONTENT_TYPE
    raise ValueError(f"unsupported document extension: {extension}")


def create_staging_presigned_post(
    *,
    batch_id: str,
    item_id: str,
    filename: str,
    content_type: str,
    size_bytes: int,
) -> dict:
    """Create a one-hour POST restricted to one staging key, MIME and size."""
    if size_bytes <= 0:
        raise ValueError("size_bytes must be positive")
    key = f"imports/{batch_id}/{item_id}/{_safe_filename(filename)}"
    return _s3_client().generate_presigned_post(
        Bucket=get_import_staging_bucket(),
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"key": key},
            {"Content-Type": content_type},
            ["content-length-range", size_bytes, size_bytes],
        ],
        ExpiresIn=PRESIGNED_POST_EXPIRY_SECONDS,
    )


def head_staging_object(key: str) -> dict:
    return _s3_client().head_object(
        Bucket=get_import_staging_bucket(),
        Key=key,
    )


def read_staging_object(key: str) -> bytes:
    response = _s3_client().get_object(
        Bucket=get_import_staging_bucket(),
        Key=key,
    )
    return response["Body"].read()


def download_staging_object_to_file(key: str, fileobj) -> int:
    """Stream one staging object to a seekable file without materializing it in RAM."""
    response = _s3_client().get_object(
        Bucket=get_import_staging_bucket(),
        Key=key,
    )
    body = response["Body"]
    total = 0
    while True:
        chunk = body.read(STREAM_CHUNK_BYTES)
        if not chunk:
            break
        fileobj.write(chunk)
        total += len(chunk)
    fileobj.seek(0)
    return total


def write_staging_child(
    *,
    batch_id: str,
    item_id: str,
    filename: str,
    data: bytes,
    content_type: str,
) -> str:
    """Persist an expanded archive child so worker retries are resumable."""
    key = f"imports/{batch_id}/expanded/{item_id}/{_safe_filename(filename)}"
    _s3_client().put_object(
        Bucket=get_import_staging_bucket(),
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return key


def delete_staging_prefix(batch_id: str) -> None:
    """Delete all temporary objects for a terminal batch."""
    client = _s3_client()
    bucket = get_import_staging_bucket()
    prefix = f"imports/{batch_id}/"
    continuation_token: str | None = None

    while True:
        request = {"Bucket": bucket, "Prefix": prefix}
        if continuation_token:
            request["ContinuationToken"] = continuation_token
        response = client.list_objects_v2(**request)
        objects = [{"Key": entry["Key"]} for entry in response.get("Contents", [])]
        if objects:
            client.delete_objects(Bucket=bucket, Delete={"Objects": objects, "Quiet": True})
        if not response.get("IsTruncated"):
            return
        continuation_token = response.get("NextContinuationToken")
        if not continuation_token:
            return


def _head_or_none(bucket: str, key: str) -> dict | None:
    try:
        return _s3_client().head_object(Bucket=bucket, Key=key)
    except KeyError:
        return None
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return None
        raise


def _canonical_metadata(candidate_id: str, candidate_name: str) -> bytes:
    payload = {
        "metadataAttributes": {
            "candidate_id": {
                "value": {"type": "STRING", "stringValue": str(candidate_id)}
            },
            "candidate_name": {
                "value": {"type": "STRING", "stringValue": candidate_name}
            },
        }
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def read_existing_canonical_document(candidate_id: str) -> bytes | None:
    """Return a legacy canonical PDF/DOCX for identity backfill when present."""
    client = _s3_client()
    for extension in (".pdf", ".docx"):
        key = f"{CANONICAL_PREFIX}/cv-{candidate_id}{extension}"
        if _head_or_none(CANONICAL_BUCKET, key) is None:
            continue
        response = client.get_object(Bucket=CANONICAL_BUCKET, Key=key)
        return response["Body"].read()
    return None


def write_canonical_candidate_document(
    *,
    candidate_id: str,
    candidate_name: str,
    filename: str,
    data: bytes,
    sha256: str,
) -> CanonicalWriteResult:
    """Write/update a canonical CV and metadata without duplicate active variants."""
    extension = _document_extension(filename)
    content_type = _content_type_for_extension(extension)
    key = f"{CANONICAL_PREFIX}/cv-{candidate_id}{extension}"
    metadata_key = f"{key}.metadata.json"

    existing = _head_or_none(CANONICAL_BUCKET, key)
    if existing and existing.get("Metadata", {}).get("document-sha256") == sha256:
        return CanonicalWriteResult(key=key, changed=False)

    client = _s3_client()
    for stale_extension in {".pdf", ".docx"} - {extension}:
        stale_key = f"{CANONICAL_PREFIX}/cv-{candidate_id}{stale_extension}"
        client.delete_object(Bucket=CANONICAL_BUCKET, Key=stale_key)
        client.delete_object(
            Bucket=CANONICAL_BUCKET,
            Key=f"{stale_key}.metadata.json",
        )

    client.put_object(
        Bucket=CANONICAL_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type,
        Metadata={"document-sha256": sha256},
    )
    client.put_object(
        Bucket=CANONICAL_BUCKET,
        Key=metadata_key,
        Body=_canonical_metadata(candidate_id, candidate_name),
        ContentType="application/json",
    )
    return CanonicalWriteResult(key=key, changed=True)