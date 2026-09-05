"""FastAPI application — PostgreSQL-backed AI Recruiter.

Endpoints:
  GET  /api/jobs/{job_id}/ranking
  POST /api/jobs/{job_id}/ranking/recalculate
  GET  /api/jobs/{job_id}/ranking/latest
  GET  /api/jobs/{job_id}/candidates
"""

import logging
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app import crud
from app.db import Base, get_engine
from app.health import router as health_router
from app.deps import (
    acquire_job_lock,
    get_current_user,
    get_db,
    release_job_lock,
)
from app.schemas import (
    CandidateResponse,
    RankingResponse,
    RecalculateResponse,
)

logger = logging.getLogger(__name__)

# ============================================================
# APP
# ============================================================

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
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)


@app.on_event("startup")
def on_startup() -> None:
    """Create tables if they don't exist (dev convenience).

    Skipped when DATABASE_URL is not a PostgreSQL URL (e.g. during tests).
    """
    import os
    db_url = os.getenv("DATABASE_URL", "")
    if "sqlite" in db_url or not db_url:
        logger.info("Skipping table creation (non-PostgreSQL URL).")
        return
    logger.info("Creating tables if not present ...")
    Base.metadata.create_all(bind=get_engine())
    logger.info("Tables ready.")


# ============================================================
# HELPER
# ============================================================

def _require_job(db: Session, job_id: str):
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")
    return job


# ============================================================
# GET /api/jobs/{job_id}/ranking
# ============================================================

@app.get(
    "/api/jobs/{job_id}/ranking",
    response_model=RankingResponse,
    summary="Consultar ranking de candidatos para una vacante",
)
def get_job_ranking(
    job_id: str,
    min_score: float = Query(0, ge=0, le=100),
    max_score: float = Query(100, ge=0, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    _require_job(db, job_id)

    if min_score > max_score:
        raise HTTPException(
            status_code=400,
            detail="min_score no puede ser mayor que max_score.",
        )

    result = crud.build_ranking_response(
        db, job_id, page=page, page_size=page_size,
    )

    # Apply score filters
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

    logger.info(
        "GET ranking job=%s total=%d page=%d",
        job_id, result["total"], page,
    )
    return result


# ============================================================
# POST /api/jobs/{job_id}/ranking/recalculate
# ============================================================

@app.post(
    "/api/jobs/{job_id}/ranking/recalculate",
    response_model=RecalculateResponse,
    summary="Recalcular ranking (full o incremental)",
)
def recalculate_ranking(
    job_id: str,
    mode: str = Query(
        "full",
        pattern=r"^(full|incremental)$",
        description="full = todos, incremental = solo nuevos",
    ),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    job = _require_job(db, job_id)

    # ── Advisory lock ──────────────────────────────────────
    acquired = acquire_job_lock(db, job_id)
    if not acquired:
        raise HTTPException(
            status_code=409,
            detail=(
                "Otro proceso está recalculando el ranking "
                "para esta vacante. Intenta de nuevo en unos segundos."
            ),
        )

    try:
        # ── Get metadata ───────────────────────────────────
        meta = crud.get_ranking_metadata(db, job_id)
        prev_version = (meta.ranking_version if meta else 0) or 0
        new_version = prev_version + 1

        # ── Determine effective mode ───────────────────────
        effective_mode = mode
        if mode == "incremental" and (not meta or not meta.generated_at):
            effective_mode = "full"
            logger.info(
                "INCREMENTAL FALLBACK job=%s — no previous ranking, using full",
                job_id,
            )

        # ── Find candidates to evaluate ────────────────────
        # For now, this skeleton always evaluates an empty set.
        # Replace with your candidate discovery logic:
        #   candidate_ids = db.query(...).filter(...)
        candidate_ids: list[str] = []

        evaluated = 0
        failures = 0

        # ── Persist ranking metadata (always) ──────────────
        ranking = crud.upsert_ranking_metadata(
            db, job_id, new_version, mode=effective_mode,
        )

        # ── Persist ranking items (empty set in skeleton) ──
        all_items: list[dict] = []
        # TODO: populate all_items with real candidate evaluations
        #   for cid in candidate_ids:
        #       score = compute_score_for_candidate(...)
        #       all_items.append({"candidate_id": cid, "score": score, "position": ...})

        if all_items:
            crud.insert_ranking_items(
                db, ranking_id=ranking.id, items=all_items,
            )

        logger.info(
            "RECALCULATE job=%s mode=%s effective=%s evaluated=%d failed=%d version=%d",
            job_id, mode, effective_mode, evaluated, failures, new_version,
        )

        return {
            "job_id": job_id,
            "mode": effective_mode,
            "total_candidates": len(candidate_ids),
            "evaluated": evaluated,
            "failed": failures,
            "ranking_version": new_version,
        }

    finally:
        release_job_lock(db, job_id)


# ============================================================
# GET /api/jobs/{job_id}/ranking/latest
# ============================================================

@app.get(
    "/api/jobs/{job_id}/ranking/latest",
    response_model=RankingResponse,
    summary="Ranking más reciente con items y candidate info",
)
def get_latest_ranking(
    job_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    _require_job(db, job_id)

    meta = crud.get_ranking_metadata(db, job_id)
    if not meta or meta.ranking_version == 0:
        raise HTTPException(
            status_code=404,
            detail="No existe ranking para esta vacante. Ejecuta recalculate primero.",
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


# ============================================================
# GET /api/jobs/{job_id}/candidates
# ============================================================

@app.get(
    "/api/jobs/{job_id}/candidates",
    response_model=list[CandidateResponse],
    summary="Candidatos asignados a una vacante (paginado)",
)
def get_job_candidates(
    job_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> list[Any]:
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
