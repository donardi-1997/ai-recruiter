"""Ranking router — FastAPI endpoints for job rankings."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app import crud
from app.domains.ranking.service import recalculate_ranking, build_latest_ranking
from app.domains.ranking.exceptions import (
    RankingJobNotFound,
    RankingNotFound,
    RankingAlreadyRunning,
)

router = APIRouter(prefix="/api/jobs", tags=["ranking"])


def _require_job(db: Session, job_id: str, owner_sub: str):
    job = crud.get_job(db, job_id, owner_sub=owner_sub)
    if not job:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")
    return job


@router.get("/{job_id}/ranking")
def get_job_ranking(
    job_id: str,
    min_score: float = Query(0, ge=0, le=100),
    max_score: float = Query(100, ge=0, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    scope: str = Query("assigned", pattern=r"^(assigned|all)$"),
    recommendation: str | None = Query(None),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id, _user["sub"])

    if min_score > max_score:
        raise HTTPException(
            status_code=400,
            detail="min_score no puede ser mayor que max_score.",
        )

    return crud.build_ranking_response(
        db,
        job_id,
        page=page,
        page_size=page_size,
        min_score=min_score,
        max_score=max_score,
        recommendation=recommendation,
        scope=scope,
    )


@router.post("/{job_id}/ranking/recalculate")
def recalculate_ranking_endpoint(
    job_id: str,
    mode: str = Query("full", pattern=r"^(full|incremental)$"),
    scope: str = Query("assigned", pattern=r"^(assigned|all)$"),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    try:
        return recalculate_ranking(
            db,
            job_id=job_id,
            owner_sub=_user["sub"],
            mode=mode,
            scope=scope,
        )
    except RankingAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=exc.message)
    except RankingJobNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message)


@router.get("/{job_id}/ranking/latest")
def get_latest_ranking_endpoint(
    job_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    try:
        return build_latest_ranking(db, job_id=job_id, owner_sub=_user["sub"])
    except RankingJobNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    except RankingNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message)