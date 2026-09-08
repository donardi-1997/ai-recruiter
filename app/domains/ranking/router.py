"""Ranking router."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.deps import (
    acquire_job_lock,
    get_current_user,
    get_db,
    release_job_lock,
)
from app import crud

router = APIRouter(prefix="/api/jobs", tags=["ranking"])


def _require_job(db: Session, job_id: str, owner_sub: str):
    job = crud.get_job(db, job_id, owner_sub=owner_sub)
    if not job:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")
    return job


FAILED_EVALUATION_PUBLIC_MESSAGE = (
    "No fue posible completar la evaluación. Intenta nuevamente."
)


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
def recalculate_ranking(
    job_id: str,
    mode: str = Query("full", pattern=r"^(full|incremental)$"),
    scope: str = Query("assigned", pattern=r"^(assigned|all)$"),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id, _user["sub"])

    acquired = acquire_job_lock(db, job_id)

    if not acquired:
        raise HTTPException(
            status_code=409,
            detail="Otro proceso esta recalculando el ranking.",
        )

    try:
        from app.evaluation import evaluate_candidate as llm_evaluate, retrieve_candidate

        job = crud.get_job(db, job_id)

        meta = crud.get_ranking_metadata(db, job_id)

        prev_version = (meta.ranking_version if meta else 0) or 0
        new_version = prev_version + 1

        effective_mode = mode
        if mode == "incremental" and (not meta or not meta.generated_at):
            effective_mode = "full"

        ranking = crud.upsert_ranking_metadata(
            db,
            job_id,
            new_version,
            mode=effective_mode,
            scope=scope,
        )

        if scope == "all":
            ranking_candidates = crud.list_candidates(db, owner_sub=_user["sub"])
        else:
            ranking_candidates = crud.list_candidates_for_job(
                db,
                job_id,
                page=1,
                page_size=100000,
                owner_sub=_user["sub"],
            )[0]

        evaluated_count = 0
        failed_count = 0
        failures = []

        all_items: list[dict] = []

        for candidate in ranking_candidates:
            evaluation = crud.get_evaluation_for_job_candidate(
                db,
                job_id,
                candidate.id,
            )

            if crud.needs_evaluation(evaluation, force=(effective_mode == "full")):
                try:
                    results = retrieve_candidate(
                        candidate_id=candidate.id,
                        question=job.description or job.title,
                    )

                    llm_result = llm_evaluate(
                        candidate_id=candidate.id,
                        job_description=job.description or job.title,
                        results=results,
                    )

                    eval_status = llm_result.get("status", "COMPLETED")

                    if eval_status == "FAILED":
                        evaluation = crud.create_evaluation(
                            db,
                            candidate_id=candidate.id,
                            job_id=job_id,
                            match_score=0.0,
                            recommendation=llm_result.get("recommendation", "EVALUATION_FAILED"),
                            summary=llm_result.get("summary", ""),
                            strengths=[],
                            gaps=[],
                            status="FAILED",
                            error_message=llm_result.get("error_message", "EVALUATION_FAILED"),
                        )

                        failed_count += 1
                        failures.append({
                            "candidate_id": candidate.id,
                            "error": llm_result.get("error_message", "EVALUATION_FAILED"),
                        })
                    else:
                        evaluation = crud.create_evaluation(
                            db,
                            candidate_id=candidate.id,
                            job_id=job_id,
                            match_score=llm_result.get("match_score", 0),
                            recommendation=llm_result.get("recommendation", "LOW_MATCH"),
                            summary=llm_result.get("summary", ""),
                            strengths=llm_result.get("strengths", []),
                            gaps=llm_result.get("gaps", []),
                            requirements=llm_result.get("requirements", []),
                            status="COMPLETED",
                            error_message=None,
                        )

                        evaluated_count += 1

                except Exception as exc:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(
                        "Evaluation failed for candidate %s: %s",
                        candidate.id,
                        exc,
                        exc_info=True,
                    )

                    failed_count += 1
                    failures.append({"candidate_id": candidate.id, "error": str(exc)})

                    evaluation = crud.create_evaluation(
                        db,
                        candidate_id=candidate.id,
                        job_id=job_id,
                        match_score=0.0,
                        recommendation="EVALUATION_FAILED",
                        summary="Evaluacion fallida.",
                        strengths=[],
                        gaps=[],
                        requirements=[],
                        status="FAILED",
                        error_message=str(exc),
                    )
            else:
                evaluated_count += 1

            if crud.is_evaluation_complete(evaluation):
                effective_status = "COMPLETED"
                score = float(evaluation.match_score)
            elif evaluation and evaluation.status == "FAILED":
                effective_status = "FAILED"
                score = 0.0
            else:
                effective_status = "PENDING"
                score = 0.0

            all_items.append({
                "candidate_id": candidate.id,
                "candidate_name": candidate.name or "",
                "score": score,
                "status": effective_status,
            })

        status_order = {
            "COMPLETED": 0,
            "FAILED": 1,
            "PENDING": 2,
        }

        all_items.sort(
            key=lambda item: (
                status_order.get(item["status"], 99),
                -float(item["score"]),
                item["candidate_name"].lower(),
                item["candidate_id"],
            )
        )

        for position, item in enumerate(all_items, start=1):
            item["position"] = position

        if all_items:
            crud.insert_ranking_items(db, ranking_id=ranking.id, items=all_items)
        else:
            crud.insert_ranking_items(db, ranking_id=ranking.id, items=[])

        return {
            "job_id": job_id,
            "mode": effective_mode,
            "scope": scope,
            "total_candidates": len(ranking_candidates),
            "evaluated": evaluated_count,
            "failed": failed_count,
            "failures": failures,
            "ranking_version": new_version,
        }

    finally:
        release_job_lock(db, job_id)


@router.get("/{job_id}/ranking/latest")
def get_latest_ranking(
    job_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id, _user["sub"])

    meta = crud.get_ranking_metadata(db, job_id)
    if not meta or meta.ranking_version == 0:
        raise HTTPException(status_code=404, detail="No existe ranking para esta vacante.")

    items = crud.get_ranking_items(db, meta.id)

    candidates = []
    for item in items:
        evaluation = crud.get_evaluation_for_job_candidate(db, job_id, item.candidate_id)

        if crud.is_evaluation_complete(evaluation):
            candidates.append({
                "position": item.position,
                "candidate_id": item.candidate_id,
                "match_score": evaluation.match_score,
                "candidate_name": item.candidate.name if item.candidate else "",
                "recommendation": evaluation.recommendation,
                "status": "COMPLETED",
                "strengths": evaluation.strengths or [],
                "gaps": evaluation.gaps or [],
                "error_message": None,
            })
        elif evaluation and evaluation.status == "FAILED":
            candidates.append({
                "position": item.position,
                "candidate_id": item.candidate_id,
                "match_score": None,
                "candidate_name": item.candidate.name if item.candidate else "",
                "recommendation": "EVALUATION_FAILED",
                "status": "FAILED",
                "strengths": [],
                "gaps": [],
                "error_message": crud._sanitize_error_message(evaluation.error_message) or "Evaluacion fallida",
            })
        else:
            candidates.append({
                "position": item.position,
                "candidate_id": item.candidate_id,
                "match_score": None,
                "candidate_name": item.candidate.name if item.candidate else "",
                "recommendation": "PENDING",
                "status": "PENDING",
                "strengths": [],
                "gaps": [],
                "error_message": "Evaluacion pendiente",
            })

    return {
        "job_id": job_id,
        "job_title": crud.get_job(db, job_id).title,
        "ranking_generated_at": meta.generated_at.isoformat() if meta.generated_at else None,
        "ranking_version": meta.ranking_version,
        "total": len(items),
        "total_pages": 1,
        "page": 1,
        "page_size": len(items),
        "pending_candidates": 0,
        "candidates": candidates,
    }