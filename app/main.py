"""FastAPI application — PostgreSQL-backed AI Recruiter."""

import logging
import os
import uuid
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import crud
from app.db import Base, get_engine
from app.health import router as health_router
from app.auth_routes import router as auth_router
from app.deps import (
    acquire_job_lock,
    get_current_user,
    get_db,
    release_job_lock,
)
from app.schemas import (
    CandidateResponse,
    JobResponse,
    RankingResponse,
    RecalculateResponse,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Recruiter API (PostgreSQL)",
    description="Ranking de candidatos con PostgreSQL + advisory locks",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "https://ai.adrianguerra.net",
        "https://air.adrianguerra.net",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno del servidor."},
    )


@app.on_event("startup")
def on_startup() -> None:
    import os
    db_url = os.getenv("DATABASE_URL", "")
    if "sqlite" in db_url or not db_url:
        logger.info("Skipping table creation (non-PostgreSQL URL).")
        return
    logger.info("Creating tables if not present ...")
    Base.metadata.create_all(bind=get_engine())
    logger.info("Tables ready.")


def _require_job(db: Session, job_id: str):
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")
    return job


def _require_candidate(db: Session, candidate_id: str):
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")
    return candidate


# ============================================================
# JOBS
# ============================================================

@app.get("/api/jobs", response_model=list[JobResponse])
def list_jobs(
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    return crud.list_jobs(db)


@app.post("/api/jobs", response_model=JobResponse, status_code=201)
def create_job(
    title: str = Query(...),
    description: str | None = Query(None),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    return crud.create_job(db, title=title, description=description)


# ============================================================
# CANDIDATES
# ============================================================

@app.get("/api/candidates", response_model=list[CandidateResponse])
def list_candidates(
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    return crud.list_candidates(db)


@app.post("/api/candidates/bulk")
async def upload_candidates_bulk(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    results = []
    errors = []
    for f in files:
        try:
            name = os.path.splitext(f.filename or "Unknown")[0]
            candidate = crud.create_candidate(db, name=name)
            results.append({
                "candidate_id": candidate.id,
                "name": candidate.name,
                "original_filename": f.filename,
                "ingestion_status": "COMPLETED",
            })
        except Exception as exc:
            logger.error("Error processing %s: %s", f.filename, exc)
            errors.append({"original_filename": f.filename, "error": str(exc)})
    return {
        "processed": len(files),
        "successful": len(results),
        "failed": len(errors),
        "candidates": results,
        "errors": errors,
    }


@app.delete("/api/candidates")
def delete_all_candidates(
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    try:
        deleted, failed = crud.delete_all_candidates(db)
        return {"deleted": deleted, "failed": failed}
    except Exception as exc:
        logger.error("Error deleting all candidates: %s", exc)
        raise HTTPException(status_code=500, detail="Error al eliminar candidatos.")


@app.delete("/api/candidates/{candidate_id}")
def delete_candidate(
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    candidate = _require_candidate(db, candidate_id)
    try:
        crud.delete_candidate(db, candidate_id)
        return {"detail": "Candidato eliminado."}
    except Exception as exc:
        logger.error("Error deleting candidate %s: %s", candidate_id, exc)
        raise HTTPException(status_code=500, detail="Error al eliminar candidato.")


@app.get("/api/candidates/{candidate_id}/download")
def download_candidate_cv(
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    candidate = _require_candidate(db, candidate_id)
    return {"download_url": None, "detail": "CV storage not configured."}


@app.post("/api/candidates/{candidate_id}/evaluate-job")
def evaluate_candidate_for_job(
    candidate_id: str,
    job_id: str = Query(...),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    candidate = _require_candidate(db, candidate_id)
    job = _require_job(db, job_id)

    evaluation = crud.create_evaluation(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        match_score=0.0,
        recommendation="LOW_MATCH",
        summary="Evaluación pendiente de implementar.",
        strengths=[],
        gaps=[],
    )

    return {
        "evaluation_id": evaluation.id,
        "candidate_id": candidate_id,
        "job_id": job_id,
        "match_score": evaluation.match_score,
        "recommendation": evaluation.recommendation,
        "summary": evaluation.summary,
        "strengths": evaluation.strengths,
        "gaps": evaluation.gaps,
    }


# ============================================================
# JOB-CANDIDATE ASSIGNMENT
# ============================================================

@app.post("/api/jobs/{job_id}/candidates")
def assign_candidates_to_job(
    job_id: str,
    body: dict,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id)
    candidate_ids = body.get("candidate_ids", [])
    if not candidate_ids:
        raise HTTPException(status_code=400, detail="candidate_ids requerido.")
    assigned, skipped = crud.assign_candidates_to_job(db, job_id, candidate_ids)
    return {"assigned": assigned, "skipped": skipped}


@app.get(
    "/api/jobs/{job_id}/candidates",
    response_model=list[CandidateResponse],
)
def get_job_candidates(
    job_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id)
    items, _total = crud.list_candidates_for_job(
        db, job_id, page=page, page_size=page_size,
    )
    return [
        CandidateResponse(
            id=c.id,
            name=c.name,
            email=c.email,
            created_at=c.created_at,
            metadata=c.metadata_,
        )
        for c in items
    ]


# ============================================================
# RANKING
# ============================================================

@app.get(
    "/api/jobs/{job_id}/ranking",
    response_model=RankingResponse,
)
def get_job_ranking(
    job_id: str,
    min_score: float = Query(0, ge=0, le=100),
    max_score: float = Query(100, ge=0, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id)

    if min_score > max_score:
        raise HTTPException(
            status_code=400,
            detail="min_score no puede ser mayor que max_score.",
        )

    result = crud.build_ranking_response(
        db, job_id, page=page, page_size=page_size,
    )

    candidates = result["candidates"]
    if min_score > 0:
        candidates = [c for c in candidates if c.get("score", 0) >= min_score]
    if max_score < 100:
        candidates = [c for c in candidates if c.get("score", 0) <= max_score]

    result["candidates"] = candidates
    result["total"] = len(candidates)
    result["total_pages"] = (
        (len(candidates) + page_size - 1) // page_size
        if candidates else 0
    )

    return result


@app.post(
    "/api/jobs/{job_id}/ranking/recalculate",
    response_model=RecalculateResponse,
)
def recalculate_ranking(
    job_id: str,
    mode: str = Query(
        "full",
        pattern=r"^(full|incremental)$",
    ),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    job = _require_job(db, job_id)

    acquired = acquire_job_lock(db, job_id)
    if not acquired:
        raise HTTPException(
            status_code=409,
            detail="Otro proceso está recalculando el ranking.",
        )

    try:
        meta = crud.get_ranking_metadata(db, job_id)
        prev_version = (meta.ranking_version if meta else 0) or 0
        new_version = prev_version + 1

        effective_mode = mode
        if mode == "incremental" and (not meta or not meta.generated_at):
            effective_mode = "full"

        candidate_ids: list[str] = []

        ranking = crud.upsert_ranking_metadata(
            db, job_id, new_version, mode=effective_mode,
        )

        all_items: list[dict] = []

        if all_items:
            crud.insert_ranking_items(
                db, ranking_id=ranking.id, items=all_items,
            )

        return {
            "job_id": job_id,
            "mode": effective_mode,
            "total_candidates": len(candidate_ids),
            "evaluated": 0,
            "failed": 0,
            "ranking_version": new_version,
        }

    finally:
        release_job_lock(db, job_id)


@app.get(
    "/api/jobs/{job_id}/ranking/latest",
    response_model=RankingResponse,
)
def get_latest_ranking(
    job_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id)

    meta = crud.get_ranking_metadata(db, job_id)
    if not meta or meta.ranking_version == 0:
        raise HTTPException(
            status_code=404,
            detail="No existe ranking para esta vacante.",
        )

    items = crud.get_ranking_items(db, meta.id)

    return {
        "job_id": job_id,
        "job_title": crud.get_job(db, job_id).title,
        "ranking_generated_at": (
            meta.generated_at.isoformat()
            if meta.generated_at
            else None
        ),
        "ranking_version": meta.ranking_version,
        "total": len(items),
        "total_pages": 1,
        "page": 1,
        "page_size": len(items),
        "pending_candidates": 0,
        "candidates": [
            {
                "position": item.position,
                "candidate_id": item.candidate_id,
                "score": item.score,
                "candidate_name": item.candidate.name if item.candidate else "",
            }
            for item in items
        ],
    }
