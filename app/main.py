"""FastAPI application — PostgreSQL-backed AI Recruiter."""

import logging
import os
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
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
    db_url = os.getenv("DATABASE_URL", "")
    if "sqlite" in db_url or not db_url:
        logger.info("Skipping table creation (non-PostgreSQL URL).")
        return
    logger.info("Creating tables if not present ...")
    Base.metadata.create_all(bind=get_engine())
    logger.info("Tables ready.")


# ============================================================
# HELPERS
# ============================================================

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
# REQUEST SCHEMAS
# ============================================================

class CreateJobRequest(BaseModel):
    title: str
    description: str | None = None


class UpdateJobRequest(BaseModel):
    title: str | None = None
    description: str | None = None


class AssignCandidatesRequest(BaseModel):
    candidate_ids: list[str]


class EvaluateRequest(BaseModel):
    job_id: str


# ============================================================
# JOBS
# ============================================================

@app.get("/api/jobs")
def list_jobs(
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    jobs = crud.list_jobs(db)
    return [
        {
            "job_id": j.id,
            "id": j.id,
            "title": j.title,
            "description": j.description,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "candidate_count": crud.count_candidates_for_job(db, j.id),
        }
        for j in jobs
    ]


@app.post("/api/jobs", status_code=201)
def create_job(
    body: CreateJobRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    job = crud.create_job(db, title=body.title, description=body.description)
    return {
        "job_id": job.id,
        "id": job.id,
        "title": job.title,
        "description": job.description,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


@app.put("/api/jobs/{job_id}")
def update_job(
    job_id: str,
    body: UpdateJobRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    job = _require_job(db, job_id)
    updated = crud.update_job(db, job, title=body.title, description=body.description)
    return {
        "job_id": updated.id,
        "id": updated.id,
        "title": updated.title,
        "description": updated.description,
        "created_at": updated.created_at.isoformat() if updated.created_at else None,
    }


@app.delete("/api/jobs/{job_id}")
def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id)
    crud.delete_job(db, job_id)
    return {"detail": "Vacante eliminada."}


# ============================================================
# CANDIDATES
# ============================================================

@app.get("/api/candidates")
def list_candidates(
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    candidates = crud.list_candidates(db)
    return [
        {
            "candidate_id": c.id,
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "metadata": c.metadata_,
            "filename": c.metadata_.get("filename") if c.metadata_ else None,
        }
        for c in candidates
    ]


@app.get("/api/candidates/{candidate_id}")
def get_candidate(
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    c = _require_candidate(db, candidate_id)
    return {
        "candidate_id": c.id,
        "id": c.id,
        "name": c.name,
        "email": c.email,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "metadata": c.metadata_,
        "filename": c.metadata_.get("filename") if c.metadata_ else None,
    }


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
            metadata = {"filename": f.filename}
            candidate = crud.create_candidate(db, name=name, metadata=metadata)
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
    _require_candidate(db, candidate_id)
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
    _require_candidate(db, candidate_id)
    return {"download_url": None, "detail": "CV storage not configured."}


@app.get("/api/candidates/{candidate_id}/evaluations")
def get_candidate_evaluations(
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_candidate(db, candidate_id)
    evaluations = crud.get_evaluations_for_candidate(db, candidate_id)
    return {
        "evaluations": [
            {
                "evaluation_id": e.id,
                "job_id": e.job_id,
                "match_score": e.match_score,
                "recommendation": e.recommendation,
                "summary": e.summary,
                "strengths": e.strengths or [],
                "gaps": e.gaps or [],
            }
            for e in evaluations
        ]
    }


@app.post("/api/candidates/{candidate_id}/evaluate-job")
def evaluate_candidate_for_job(
    candidate_id: str,
    body: EvaluateRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    from app.evaluation import evaluate_candidate as llm_evaluate, retrieve_candidate

    candidate = _require_candidate(db, candidate_id)
    job = _require_job(db, body.job_id)

    try:
        results = retrieve_candidate(
            candidate_id=candidate_id,
            question=job.description or job.title,
        )
        llm_result = llm_evaluate(
            candidate_id=candidate_id,
            job_description=job.description or job.title,
            results=results,
        )

        # Check if evaluation actually succeeded
        eval_status = llm_result.get("status", "COMPLETED")
        if eval_status == "FAILED":
            evaluation = crud.create_evaluation(
                db,
                candidate_id=candidate_id,
                job_id=body.job_id,
                match_score=0,
                recommendation=llm_result.get("recommendation", "EVALUATION_FAILED"),
                summary=llm_result.get("summary", ""),
                strengths=[],
                gaps=[],
                status="FAILED",
                error_message=llm_result.get("error_message", "EVALUATION_FAILED"),
            )
        else:
            evaluation = crud.create_evaluation(
                db,
                candidate_id=candidate_id,
                job_id=body.job_id,
                match_score=llm_result.get("match_score", 0),
                recommendation=llm_result.get("recommendation", "LOW_MATCH"),
                summary=llm_result.get("summary", ""),
                strengths=llm_result.get("strengths", []),
                gaps=llm_result.get("gaps", []),
                status="COMPLETED",
            )
    except Exception as exc:
        logger.error("LLM evaluation failed for candidate %s: %s", candidate_id, exc, exc_info=True)
        evaluation = crud.create_evaluation(
            db,
            candidate_id=candidate_id,
            job_id=body.job_id,
            match_score=0.0,
            recommendation="EVALUATION_FAILED",
            summary=f"Evaluacion fallida: {exc}",
            strengths=[],
            gaps=[],
            status="FAILED",
            error_message=str(exc),
        )

    return {
        "evaluation_id": evaluation.id,
        "candidate_id": candidate_id,
        "job_id": body.job_id,
        "match_score": evaluation.match_score,
        "recommendation": evaluation.recommendation,
        "summary": evaluation.summary,
        "strengths": evaluation.strengths or [],
        "gaps": evaluation.gaps or [],
    }


# ============================================================
# JOB-CANDIDATE ASSIGNMENT
# ============================================================

@app.post("/api/jobs/{job_id}/candidates")
def assign_candidates_to_job(
    job_id: str,
    body: AssignCandidatesRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id)
    if not body.candidate_ids:
        raise HTTPException(status_code=400, detail="candidate_ids requerido.")
    assigned, skipped = crud.assign_candidates_to_job(db, job_id, body.candidate_ids)
    return {"assigned": assigned, "skipped": skipped}


@app.get("/api/jobs/{job_id}/candidates")
def get_job_candidates(
    job_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id)
    items, total = crud.list_candidates_for_job(
        db, job_id, page=page, page_size=page_size,
    )
    return [
        {
            "candidate_id": c.id,
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "metadata": c.metadata_,
            "filename": c.metadata_.get("filename") if c.metadata_ else None,
        }
        for c in items
    ]


@app.get("/api/jobs/{job_id}/candidates/{candidate_id}")
def get_job_candidate_detail(
    job_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id)
    _require_candidate(db, candidate_id)
    evaluation = crud.get_evaluation_for_job_candidate(db, job_id, candidate_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluacion no encontrada.")
    return {
        "evaluation_id": evaluation.id,
        "candidate_id": evaluation.candidate_id,
        "job_id": evaluation.job_id,
        "match_score": evaluation.match_score,
        "recommendation": evaluation.recommendation,
        "summary": evaluation.summary,
        "strengths": evaluation.strengths or [],
        "gaps": evaluation.gaps or [],
    }


@app.get("/api/jobs/{job_id}/candidates/{candidate_id}/explanation")
def get_candidate_explanation(
    job_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id)
    _require_candidate(db, candidate_id)
    evaluation = crud.get_evaluation_for_job_candidate(db, job_id, candidate_id)
    return {
        "explanation": evaluation.summary if evaluation else "Sin evaluacion.",
        "summary": evaluation.summary if evaluation else None,
        "analysis": None,
    }


@app.get("/api/jobs/{job_id}/candidates/{candidate_id}/requirements")
def get_candidate_requirements(
    job_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id)
    _require_candidate(db, candidate_id)
    evaluation = crud.get_evaluation_for_job_candidate(db, job_id, candidate_id)
    requirements = []
    if evaluation and evaluation.strengths:
        for s in evaluation.strengths:
            requirements.append({"requirement": s, "status": "MATCH", "evidence": None})
    if evaluation and evaluation.gaps:
        for g in evaluation.gaps:
            requirements.append({"requirement": g, "status": "MISSING", "evidence": None})
    return {"requirements": requirements}


# ============================================================
# RANKING
# ============================================================

@app.get("/api/jobs/{job_id}/ranking")
def get_job_ranking(
    job_id: str,
    min_score: float = Query(0, ge=0, le=100),
    max_score: float = Query(100, ge=0, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    scope: str = Query("assigned"),
    recommendation: str | None = Query(None),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id)

    if min_score > max_score:
        raise HTTPException(status_code=400, detail="min_score no puede ser mayor que max_score.")

    result = crud.build_ranking_response(db, job_id, page=page, page_size=page_size)

    candidates = result["candidates"]
    if min_score > 0:
        candidates = [c for c in candidates if c.get("match_score", 0) >= min_score]
    if max_score < 100:
        candidates = [c for c in candidates if c.get("match_score", 0) <= max_score]

    result["candidates"] = candidates
    result["total"] = len(candidates)
    result["total_pages"] = (len(candidates) + page_size - 1) // page_size if candidates else 0

    return result


@app.post("/api/jobs/{job_id}/ranking/recalculate")
def recalculate_ranking(
    job_id: str,
    mode: str = Query("full", pattern=r"^(full|incremental)$"),
    scope: str = Query("assigned"),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id)

    acquired = acquire_job_lock(db, job_id)
    if not acquired:
        raise HTTPException(status_code=409, detail="Otro proceso esta recalculando el ranking.")

    try:
        from app.evaluation import evaluate_candidate as llm_evaluate, retrieve_candidate

        job = crud.get_job(db, job_id)
        meta = crud.get_ranking_metadata(db, job_id)
        prev_version = (meta.ranking_version if meta else 0) or 0
        new_version = prev_version + 1

        effective_mode = mode
        if mode == "incremental" and (not meta or not meta.generated_at):
            effective_mode = "full"

        ranking = crud.upsert_ranking_metadata(db, job_id, new_version, mode=effective_mode)

        assigned_candidates = crud.list_candidates_for_job(db, job_id, page=1, page_size=1000)[0]

        evaluated_count = 0
        failed_count = 0
        failures = []

        all_items: list[dict] = []
        for position, candidate in enumerate(assigned_candidates, start=1):
            evaluation = crud.get_evaluation_for_job_candidate(db, job_id, candidate.id)

            needs_evaluation = (
                evaluation is None
                or effective_mode == "full"
                or evaluation.status == "FAILED"
                or evaluation.recommendation == "EVALUATION_FAILED"
            )

            if needs_evaluation:
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

                    # Check if evaluation actually succeeded
                    eval_status = llm_result.get("status", "COMPLETED")
                    if eval_status == "FAILED":
                        evaluation = crud.create_evaluation(
                            db,
                            candidate_id=candidate.id,
                            job_id=job_id,
                            match_score=0,
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
                            status="COMPLETED",
                        )
                        evaluated_count += 1
                except Exception as exc:
                    logger.error("Evaluation failed for candidate %s: %s", candidate.id, exc, exc_info=True)
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
                        status="FAILED",
                        error_message=str(exc),
                    )
            else:
                evaluated_count += 1

            score = evaluation.match_score if evaluation else 0.0
            all_items.append({
                "candidate_id": candidate.id,
                "score": score,
                "position": position,
            })

        if all_items:
            crud.insert_ranking_items(db, ranking_id=ranking.id, items=all_items)

        return {
            "job_id": job_id,
            "mode": effective_mode,
            "total_candidates": len(assigned_candidates),
            "evaluated": evaluated_count,
            "failed": failed_count,
            "failures": failures,
            "ranking_version": new_version,
        }
    finally:
        release_job_lock(db, job_id)


@app.get("/api/jobs/{job_id}/ranking/latest")
def get_latest_ranking(
    job_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id)

    meta = crud.get_ranking_metadata(db, job_id)
    if not meta or meta.ranking_version == 0:
        raise HTTPException(status_code=404, detail="No existe ranking para esta vacante.")

    items = crud.get_ranking_items(db, meta.id)

    candidates = []
    for item in items:
        evaluation = crud.get_evaluation_for_job_candidate(db, job_id, item.candidate_id)
        candidates.append({
            "position": item.position,
            "candidate_id": item.candidate_id,
            "match_score": evaluation.match_score if evaluation else item.score,
            "candidate_name": item.candidate.name if item.candidate else "",
            "recommendation": evaluation.recommendation if evaluation else "PENDING",
            "status": evaluation.status if evaluation else "PENDING",
            "strengths": evaluation.strengths if evaluation and evaluation.strengths else [],
            "gaps": evaluation.gaps if evaluation and evaluation.gaps else [],
            "error_message": evaluation.error_message if evaluation else None,
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
