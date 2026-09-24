"""S3 adapter for persistent training videos."""

from __future__ import annotations

import re
import uuid
from pathlib import PurePosixPath

from botocore.exceptions import ClientError

from app.config import get_aws_region, get_training_content_bucket
from app.infrastructure.bedrock.session import get_cached_session

PRESIGNED_UPLOAD_EXPIRY_SECONDS = 3600
PRESIGNED_PLAYBACK_EXPIRY_SECONDS = 3600
MAX_TRAINING_VIDEO_BYTES = 1024 * 1024 * 1024

ALLOWED_VIDEO_TYPES = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/ogg": ".ogv",
}


def _s3_client():
    return get_cached_session().client("s3", region_name=get_aws_region())


def _safe_filename(filename: str) -> str:
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", basename).strip("._")
    return safe or "video"


def _validate_upload(*, filename: str, content_type: str, size_bytes: int) -> str:
    if content_type not in ALLOWED_VIDEO_TYPES:
        raise ValueError("unsupported training video content type")
    if size_bytes <= 0 or size_bytes > MAX_TRAINING_VIDEO_BYTES:
        raise ValueError("training video size is outside the allowed range")

    expected_extension = ALLOWED_VIDEO_TYPES[content_type]
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.casefold()
    accepted = {expected_extension}
    if content_type == "video/ogg":
        accepted.add(".ogg")
    if suffix not in accepted:
        raise ValueError("training video extension does not match content type")
    return expected_extension


def create_video_upload(
    *,
    lesson_id: str,
    filename: str,
    content_type: str,
    size_bytes: int,
) -> dict:
    """Create an exact-size presigned POST for one immutable training object."""

    extension = _validate_upload(
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
    )
    safe_name = _safe_filename(filename)
    key = f"training/lessons/{lesson_id}/{uuid.uuid4().hex}-{safe_name}"
    if not key.casefold().endswith(extension) and not (
        content_type == "video/ogg" and key.casefold().endswith(".ogg")
    ):
        raise ValueError("invalid training video object key")

    upload = _s3_client().generate_presigned_post(
        Bucket=get_training_content_bucket(),
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"key": key},
            {"Content-Type": content_type},
            ["content-length-range", size_bytes, size_bytes],
        ],
        ExpiresIn=PRESIGNED_UPLOAD_EXPIRY_SECONDS,
    )
    return {
        "key": key,
        "upload": upload,
        "expires_in": PRESIGNED_UPLOAD_EXPIRY_SECONDS,
        "max_size_bytes": MAX_TRAINING_VIDEO_BYTES,
    }


def verify_video_object(
    *,
    lesson_id: str,
    key: str,
    expected_content_type: str,
    expected_size_bytes: int,
) -> dict:
    """Verify an uploaded object belongs to the lesson and matches its manifest."""

    prefix = f"training/lessons/{lesson_id}/"
    if not key.startswith(prefix):
        raise ValueError("training video key does not belong to lesson")
    if expected_content_type not in ALLOWED_VIDEO_TYPES:
        raise ValueError("unsupported training video content type")
    if expected_size_bytes <= 0 or expected_size_bytes > MAX_TRAINING_VIDEO_BYTES:
        raise ValueError("training video size is outside the allowed range")

    response = _s3_client().head_object(
        Bucket=get_training_content_bucket(),
        Key=key,
    )
    actual_size = int(response.get("ContentLength") or 0)
    actual_type = str(response.get("ContentType") or "").split(";", 1)[0].strip().casefold()

    if actual_size != expected_size_bytes:
        raise ValueError("uploaded training video size does not match manifest")
    if actual_type != expected_content_type:
        raise ValueError("uploaded training video content type does not match manifest")

    return {
        "key": key,
        "content_type": actual_type,
        "size_bytes": actual_size,
    }


def create_video_playback_url(
    key: str,
    *,
    expires_in: int = PRESIGNED_PLAYBACK_EXPIRY_SECONDS,
) -> str:
    """Return a short-lived private playback URL."""

    if not key.startswith("training/lessons/"):
        raise ValueError("invalid training video key")
    bounded_expiry = max(60, min(int(expires_in), 3600))
    return _s3_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": get_training_content_bucket(),
            "Key": key,
        },
        ExpiresIn=bounded_expiry,
    )


def delete_video_object(key: str) -> None:
    if not key.startswith("training/lessons/"):
        raise ValueError("invalid training video key")
    _s3_client().delete_object(
        Bucket=get_training_content_bucket(),
        Key=key,
    )


def video_object_exists(key: str) -> bool:
    try:
        _s3_client().head_object(
            Bucket=get_training_content_bucket(),
            Key=key,
        )
        return True
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return False
        raise
