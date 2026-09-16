"""S3 storage adapter for provider-neutral candidate ingestion source documents."""

from __future__ import annotations

import re

from app.config import get_aws_region, get_import_staging_bucket
from app.infrastructure.bedrock.session import get_cached_session


def _safe_segment(value: str, *, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("._")
    return cleaned or fallback


class EmailIngestionStorage:
    """Persist raw email attachments in the existing private import staging bucket."""

    def _s3_client(self):
        return get_cached_session().client("s3", region_name=get_aws_region())

    def store_source_document(
        self,
        *,
        event_id: str,
        attachment_id: str,
        filename: str,
        data: bytes,
        content_type: str,
    ) -> str:
        safe_attachment_id = _safe_segment(attachment_id, fallback="attachment")
        safe_filename = _safe_segment(filename.replace("\\", "/").rsplit("/", 1)[-1], fallback="resume")
        key = (
            f"candidate-ingestion/{event_id}/source/"
            f"{safe_attachment_id}/{safe_filename}"
        )
        self._s3_client().put_object(
            Bucket=get_import_staging_bucket(),
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key
