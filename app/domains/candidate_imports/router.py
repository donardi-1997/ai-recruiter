"""Candidate-import HTTP router."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.domains.candidate_imports import presenter, service
from app.domains.candidate_imports.exceptions import (
    ImportBatchNotFound,
    InvalidImportManifest,
    JobNotFound,
    QueueDispatchFailed,
    UploadVerificationFailed,
)
from app.domains.candidate_imports.schemas import CreateImportBatchRequest

router = APIRouter(prefix="/api/import-batches", tags=["candidate-imports"])


def _batch_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Importacion no encontrada.")


def _job_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Vacante no encontrada.")


@router.post("", status_code=202)
def create_import_batch(
    body: CreateImportBatchRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        batch, uploads = service.create_batch(
            db,
            owner_sub=user["sub"],
            job_id=body.job_id,
            uploads=[item.model_dump() for item in body.uploads],
        )
    except JobNotFound:
        raise _job_not_found()
    except InvalidImportManifest:
        raise HTTPException(status_code=400, detail="Archivos de importacion invalidos.")

    return presenter.batch_created_payload(batch, uploads)


@router.post("/{batch_id}/complete")
def complete_import_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        batch = service.complete_batch_uploads(
            db,
            owner_sub=user["sub"],
            batch_id=batch_id,
        )
    except ImportBatchNotFound:
        raise _batch_not_found()
    except UploadVerificationFailed:
        raise HTTPException(
            status_code=400,
            detail="No se pudieron verificar todos los archivos de la importacion.",
        )
    except QueueDispatchFailed:
        raise HTTPException(
            status_code=503,
            detail="No se pudo iniciar la importacion. Intenta de nuevo.",
        )

    return presenter.batch_progress_payload(batch)


@router.get("")
def list_recent_import_batches(
    job_id: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        batches = service.list_recent_batches(
            db,
            owner_sub=user["sub"],
            job_id=job_id,
            limit=limit,
        )
    except JobNotFound:
        raise _job_not_found()

    return presenter.recent_batches_payload(batches)


@router.get("/{batch_id}")
def get_import_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        batch = service.get_batch(
            db,
            owner_sub=user["sub"],
            batch_id=batch_id,
        )
    except ImportBatchNotFound:
        raise _batch_not_found()

    return presenter.batch_progress_payload(batch)


@router.get("/{batch_id}/items")
def list_import_batch_items(
    batch_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        items, total = service.list_batch_items(
            db,
            owner_sub=user["sub"],
            batch_id=batch_id,
            page=page,
            page_size=page_size,
        )
    except ImportBatchNotFound:
        raise _batch_not_found()

    return presenter.batch_items_payload(
        items,
        total=total,
        page=page,
        page_size=page_size,
    )
