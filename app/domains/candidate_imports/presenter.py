"""Public payload presenters for candidate imports."""

from __future__ import annotations

from datetime import timedelta

from app.models import ImportBatch, ImportItem


def _iso(value):
    return value.isoformat() if value is not None else None


def batch_created_payload(batch: ImportBatch, uploads: list[dict]) -> dict:
    return {
        "batch_id": batch.id,
        "status": batch.status,
        "current_stage": batch.current_stage,
        "uploads": uploads,
        "expires_at": _iso(batch.created_at + timedelta(hours=1)),
    }


def batch_progress_payload(batch: ImportBatch) -> dict:
    return {
        "id": batch.id,
        "job_id": batch.job_id,
        "status": batch.status,
        "current_stage": batch.current_stage,
        "upload_total": batch.upload_total,
        "uploaded_items": batch.uploaded_items,
        "total_items": batch.total_items,
        "processed_items": batch.processed_items,
        "successful_items": batch.successful_items,
        "reused_items": batch.reused_items,
        "failed_items": batch.failed_items,
        "evaluated_items": batch.evaluated_items,
        "evaluation_failed_items": batch.evaluation_failed_items,
        "ranking_ready": batch.ranking_ready,
        "ranking_version": batch.ranking_version,
        "last_error_code": batch.last_error_code,
        "last_error_message": batch.last_error_message,
        "created_at": _iso(batch.created_at),
        "started_at": _iso(batch.started_at),
        "completed_at": _iso(batch.completed_at),
        "updated_at": _iso(batch.updated_at),
    }


def import_item_payload(item: ImportItem) -> dict:
    return {
        "id": item.id,
        "parent_item_id": item.parent_item_id,
        "kind": item.kind,
        "filename": item.original_filename,
        "content_type": item.content_type,
        "size_bytes": item.size_bytes,
        "candidate_id": item.candidate_id,
        "status": item.status,
        "current_stage": item.current_stage,
        "outcome": item.outcome,
        "error_code": item.error_code,
        "error_message": item.error_message,
        "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
        "completed_at": _iso(item.completed_at),
    }


def batch_items_payload(items: list[ImportItem], *, total: int, page: int, page_size: int) -> dict:
    return {
        "items": [import_item_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def recent_batches_payload(batches: list[ImportBatch]) -> dict:
    return {"items": [batch_progress_payload(batch) for batch in batches]}
