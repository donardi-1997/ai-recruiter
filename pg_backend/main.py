"""FastAPI application — PostgreSQL-backed AI Recruiter.

Endpoints:
  GET  /api/jobs/{job_id}/ranking
  POST /api/jobs/{job_id}/ranking/recalculate?mode=incremental|full
  GET  /api/jobs/{job_id}/candidates
"""

import logging
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from pg_backend.crud import (
    acquire_job_lock,
    get_evaluation,
    get_job,
    get_new_candidate_ids,
    get_ranking_for_job,
    get_ranking_metadata,
    get_ranking_items,
    get_candidate,
    insert_ranking_items,
    release_job_lock,
    upsert_evaluation,
    upsert_ranking_metadata,
)
from pg_backend.database import Base, engine, get_db
from pg_backend.models import Candidate, Evaluation, JobCandidate
from pg_backend.schemas import (
    CandidateResponse,
    RecalculateResponse,
    RankingMetadataResponse,
)

logger = logging.getLogger(__name__)

# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="AI Recruiter API (PostgreSQL)",
    description="Ranking de candidatos con PostgreSQL + advisory locks",
    version="1.0.0",
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


@app.on_event("startup")
def on_startup() -> None:
    """Create tables if they don't exist (dev convenience)."""
    logger.info("Creating tables if not present ...")
    Base.metadata.create_all(bind=engine)
    logger.info("Tables ready.")


# ============================================================
# HELPER: own the job
# ============================================================

def _require_job(db: Session, job_id: str) -> Job:
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")
    return job


# ============================================================
# GET /api/jobs/{job_id}/ranking
# ============================================================

@app.get(
    "/api/jobs/{job_id}/ranking",
    response_model=RankingMetadataResponse,
    summary="Consultar ranking de candidatos para una vacante",
)
def get_job_ranking(
    job_id: str,
    min_score: int   = Query(0, ge=0, le=100),
    max_score: int   = Query(100, ge=0, le=100),
    recommendation: str | None = Query(None),
    page: int        = Query(1, ge=1),
    page_size: int   = Query(10, ge=1, le=100),
    db: Session      = Depends(get_db),
) -> dict[str, Any]:
    _require_job(db, job_id)

    if min_score > max_score:
        raise HTTPException(
            status_code=400,
            detail="min_score no puede ser mayor que max_score.",
        )

    result = get_ranking_for_job(
        db,
        job_id,
        min_score=min_score,
        max_score=max_score,
        recommendation=recommendation,
        page=page,
        page_size=page_size,
    )

    logger.info(
        "GET ranking job=%s total=%d page=%d",
        job_id,
        result["total"],
        page,
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
        pattern="^(full|incremental)$",
        description="full = todos, incremental = solo nuevos",
    ),
    db: Session = Depends(get_db),
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
        # ── Candidate pool ─────────────────────────────────
        meta = get_ranking_metadata(db, job_id)

        if mode == "incremental" and meta and meta.ranking_generated_at:
            candidate_ids = list(get_new_candidate_ids(
                db,
                job_id,
                owner_id=job.owner_id,
                since=meta.ranking_generated_at,
            ))
        else:
            # full mode or first run
            candidate_ids = [
                r[0]
                for r in (
                    db.query(JobCandidate.candidate_id)
                    .filter(JobCandidate.job_id == job_id)
                    .all()
                )
            ]

        evaluated = 0
        failures  = 0

        for cid in candidate_ids:
            candidate = get_candidate(db, cid)
            if not candidate:
                failures += 1
                continue

            # NOTE: In production, call your LLM / Bedrock evaluator
            # here.  For the scaffold we reuse any existing evaluation
            # or create a placeholder.
            existing = get_evaluation(db, job_id, cid)
            if existing:
                # Already evaluated — skip or re-evaluate (full mode)
                if mode == "incremental":
                    evaluated += 1
                    continue

            # Placeholder scoring — replace with real LLM call
            match_score    = existing.match_score if existing else 0
            recommendation = existing.recommendation if existing else "PENDING"
            requirements   = existing.requirements if existing else []
            strengths      = existing.strengths if existing else []
            gaps           = existing.gaps if existing else []
            summary        = existing.summary if existing else ""

            try:
                upsert_evaluation(
                    db,
                    job_id,
                    cid,
                    job.owner_id,
                    job_title=job.title,
                    job_description=job.description,
                    candidate_name=candidate.name,
                    match_score=match_score,
                    recommendation=recommendation,
                    requirements=requirements,
                    strengths=strengths,
                    gaps=gaps,
                    summary=summary,
                )
                evaluated += 1
            except Exception as exc:
                logger.exception("Evaluation failed cid=%s: %s", cid, exc)
                failures += 1

        # ── Bump ranking version ───────────────────────────
        prev_version = (meta.ranking_version if meta else 0) or 0
        new_version  = prev_version + 1
        upsert_ranking_metadata(db, job_id, new_version)

        # ── Snapshot ranking items ─────────────────────────
        ranking_data = get_ranking_for_job(db, job_id, page=1, page_size=1000)
        items = [
            {
                "candidate_id": c["candidate_id"],
                "candidate_name": c["candidate_name"],
                "match_score": c["match_score"],
                "recommendation": c["recommendation"],
                "rank_position": c["rank"],
                "strengths": c["strengths"],
                "gaps": c["gaps"],
            }
            for c in ranking_data["candidates"]
        ]
        if items:
            insert_ranking_items(db, job_id, new_version, items)

        logger.info(
            "RECALCULATE job=%s mode=%s evaluated=%d failed=%d version=%d",
            job_id,
            mode,
            evaluated,
            failures,
            new_version,
        )

        return {
            "job_id": job_id,
            "mode": mode,
            "total_candidates": len(candidate_ids),
            "evaluated": evaluated,
            "failed": failures,
            "ranking_version": new_version,
        }

    finally:
        release_job_lock(db, job_id)


# ============================================================
# GET /api/jobs/{job_id}/candidates
# ============================================================

@app.get(
    "/api/jobs/{job_id}/candidates",
    response_model=list[CandidateResponse],
    summary="Candidatos asignados a una vacante",
)
def get_job_candidates(
    job_id: str,
    db: Session = Depends(get_db),
) -> list[Any]:
    _require_job(db, job_id)

    rows = (
        db.query(
            Candidate.candidate_id,
            Candidate.owner_id,
            Candidate.name,
            Candidate.filename,
            Candidate.s3_location,
            Candidate.ingestion_status,
            Candidate.indexed,
            Candidate.created_at,
        )
        .join(
            JobCandidate,
            JobCandidate.candidate_id == Candidate.candidate_id,
        )
        .filter(JobCandidate.job_id == job_id)
        .order_by(Candidate.name)
        .all()
    )

    return [
        CandidateResponse(
            candidate_id=r.candidate_id,
            owner_id=r.owner_id,
            name=r.name,
            filename=r.filename,
            s3_location=r.s3_location,
            ingestion_status=r.ingestion_status,
            indexed=r.indexed,
            created_at=r.created_at,
        )
        for r in rows
    ]
