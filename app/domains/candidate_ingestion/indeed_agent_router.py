"""Least-privilege HTTP API for the local Indeed resume download agent."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Header, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.deps import get_db
from app.domains.candidate_ingestion import indeed_email_agent_service as service
from app.domains.candidate_ingestion import indeed_agent_sync, indeed_job_sync
from app.domains.candidate_ingestion.indeed_agent_auth import (
    AgentPrincipal,
    get_indeed_resume_agent_principal,
)

router = APIRouter(prefix="/api/agents/indeed-resume", tags=["indeed-resume-agent"])


class ClaimResponse(BaseModel):
    task_id: str
    candidate_name: str
    job_title: str
    resume_url: str
    lease_token: str
    lease_expires_at: datetime


class HeartbeatResponse(BaseModel):
    lease_expires_at: datetime


class FailureRequest(BaseModel):
    code: str = Field(
        default="RESUME_DOWNLOAD_FAILED",
        min_length=3,
        max_length=120,
        pattern=r"^[A-Z0-9_]+$",
    )


class UploadResponse(BaseModel):
    document_id: str
    filename: str
    document_sha256: str | None = None


class VacancySnapshotRequest(BaseModel):
    external_job_key: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=1000)
    description: str = Field(default="", max_length=200000)
    status: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=1000)
    posted_at: str | None = Field(default=None, max_length=200)


class VacancySyncRequest(BaseModel):
    snapshots: list[VacancySnapshotRequest] = Field(default_factory=list, max_length=500)


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, service.ResumeTaskNotFound):
        return HTTPException(status_code=404, detail="Resume task not found.")
    if isinstance(
        exc,
        (
            service.ResumeTaskLeaseConflict,
            service.ResumeTaskStateConflict,
            service.ResumeUploadConflict,
        ),
    ):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, service.ResumeUploadValidationError):
        return HTTPException(status_code=exc.status_code, detail=exc.code)
    if isinstance(exc, service.ResumeClaimResolutionError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail="Error interno del servidor.")


def _lease_header(
    lease_token: str | None = Header(default=None, alias="X-ASIATI-Lease-Token"),
) -> str:
    value = str(lease_token or "").strip()
    if not value:
        raise HTTPException(status_code=409, detail="RESUME_TASK_LEASE_INVALID")
    return value


@router.post("/claim", response_model=ClaimResponse, responses={204: {"description": "Queue empty"}})
def claim_resume_task(
    db: Session = Depends(get_db),
    principal: AgentPrincipal = Depends(get_indeed_resume_agent_principal),
):
    try:
        claimed = service.claim_next_task_with_resume_url(
            db,
            owner_sub=principal.owner_sub,
        )
    except Exception as exc:
        raise _translate(exc)
    if claimed is None:
        return Response(status_code=204)
    return ClaimResponse(
        task_id=claimed.task_id,
        candidate_name=claimed.candidate_name,
        job_title=claimed.job_title,
        resume_url=claimed.resume_url,
        lease_token=claimed.lease_token,
        lease_expires_at=claimed.lease_expires_at,
    )


@router.post("/jobs/sync")
def synchronize_indeed_jobs(
    payload: VacancySyncRequest,
    db: Session = Depends(get_db),
    principal: AgentPrincipal = Depends(get_indeed_resume_agent_principal),
):
    """Idempotently reconcile normalized vacancy snapshots from Indeed Employers."""
    try:
        return indeed_job_sync.sync_vacancy_snapshots(
            db,
            owner_sub=principal.owner_sub,
            snapshots=[item.model_dump() for item in payload.snapshots],
        )
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=502, detail="RESUME_JOB_SYNC_FAILED")


@router.post("/{task_id}/heartbeat", response_model=HeartbeatResponse)
def heartbeat_resume_task(
    task_id: str,
    db: Session = Depends(get_db),
    principal: AgentPrincipal = Depends(get_indeed_resume_agent_principal),
    lease_token: str = Depends(_lease_header),
):
    try:
        expires_at = service.heartbeat(
            db,
            owner_sub=principal.owner_sub,
            task_id=task_id,
            lease_token=lease_token,
        )
        return HeartbeatResponse(lease_expires_at=expires_at)
    except Exception as exc:
        raise _translate(exc)


@router.post("/{task_id}/resume", response_model=UploadResponse)
async def upload_resume(
    task_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: AgentPrincipal = Depends(get_indeed_resume_agent_principal),
    lease_token: str = Depends(_lease_header),
):
    data = await file.read(service.MAX_DOCUMENT_BYTES + 1)
    if len(data) > service.MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="RESUME_TOO_LARGE")
    try:
        document = service.store_resume_document(
            db,
            owner_sub=principal.owner_sub,
            task_id=task_id,
            lease_token=lease_token,
            filename=file.filename,
            content_type=file.content_type or "",
            data=data,
        )
    except Exception as exc:
        raise _translate(exc)
    return UploadResponse(
        document_id=document.id,
        filename=document.filename,
        document_sha256=document.document_sha256,
    )


@router.post("/{task_id}/needs-human")
def needs_human(
    task_id: str,
    payload: FailureRequest,
    db: Session = Depends(get_db),
    principal: AgentPrincipal = Depends(get_indeed_resume_agent_principal),
    lease_token: str = Depends(_lease_header),
):
    try:
        service.mark_needs_human(
            db,
            owner_sub=principal.owner_sub,
            task_id=task_id,
            lease_token=lease_token,
            code=payload.code,
        )
    except Exception as exc:
        raise _translate(exc)
    return {"status": "NEEDS_HUMAN"}


@router.post("/{task_id}/fail")
def fail_resume_task(
    task_id: str,
    payload: FailureRequest,
    db: Session = Depends(get_db),
    principal: AgentPrincipal = Depends(get_indeed_resume_agent_principal),
    lease_token: str = Depends(_lease_header),
):
    try:
        status = service.record_failure(
            db,
            owner_sub=principal.owner_sub,
            task_id=task_id,
            lease_token=lease_token,
            code=payload.code,
        )
    except Exception as exc:
        raise _translate(exc)
    return {"status": status}


@router.post("/{task_id}/resume-after-human")
def resume_task_after_human(
    task_id: str,
    db: Session = Depends(get_db),
    principal: AgentPrincipal = Depends(get_indeed_resume_agent_principal),
):
    try:
        service.resume_after_human(
            db,
            owner_sub=principal.owner_sub,
            task_id=task_id,
        )
    except Exception as exc:
        raise _translate(exc)
    return {"status": "WAITING_DOWNLOAD"}


@router.post("/retry-failed")
def retry_failed_resume_tasks(
    db: Session = Depends(get_db),
    principal: AgentPrincipal = Depends(get_indeed_resume_agent_principal),
):
    try:
        count = service.requeue_failed_tasks(
            db,
            owner_sub=principal.owner_sub,
        )
    except Exception as exc:
        raise _translate(exc)
    return {"status": "WAITING_DOWNLOAD", "requeued": count}


@router.post("/retry-attention")
def retry_attention_resume_tasks(
    db: Session = Depends(get_db),
    principal: AgentPrincipal = Depends(get_indeed_resume_agent_principal),
):
    try:
        count = service.requeue_needs_human_tasks(
            db,
            owner_sub=principal.owner_sub,
        )
    except Exception as exc:
        raise _translate(exc)
    return {"status": "WAITING_DOWNLOAD", "requeued": count}


@router.post("/sync")
def synchronize_resume_sources(
    db: Session = Depends(get_db),
    principal: AgentPrincipal = Depends(get_indeed_resume_agent_principal),
):
    """Synchronize one bounded discovery page using the durable Gmail cursor."""
    try:
        return indeed_agent_sync.sync_one_page(
            db,
            owner_sub=principal.owner_sub,
        )
    except HTTPException:
        raise
    except indeed_agent_sync.ResumeSyncStageError as exc:
        raise HTTPException(status_code=502, detail=exc.code)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=502, detail="RESUME_SYNC_FAILED")


@router.get("/stats")
def resume_agent_stats(
    db: Session = Depends(get_db),
    principal: AgentPrincipal = Depends(get_indeed_resume_agent_principal),
):
    return service.stats(db, owner_sub=principal.owner_sub)
