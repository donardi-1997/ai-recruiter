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

def _require_job(
    db: Session,
    job_id: str,
    owner_sub: str,
):
    job = crud.get_job(
        db,
        job_id,
        owner_sub=owner_sub,
    )

    if not job:
        # 404 intentionally avoids leaking whether
        # another user's resource exists.
        raise HTTPException(
            status_code=404,
            detail="Vacante no encontrada.",
        )

    return job


def _require_candidate(
    db: Session,
    candidate_id: str,
    owner_sub: str,
):
    candidate = crud.get_candidate(
        db,
        candidate_id,
        owner_sub=owner_sub,
    )

    if not candidate:
        raise HTTPException(
            status_code=404,
            detail="Candidato no encontrado.",
        )

    return candidate


FAILED_EVALUATION_PUBLIC_MESSAGE = (
    "No fue posible completar la evaluación. Intenta nuevamente."
)


def _public_evaluation_payload(evaluation) -> dict[str, Any]:
    """Serialize an Evaluation without exposing technical failure details."""
    failed = evaluation.status == "FAILED"

    return {
        "evaluation_id": evaluation.id,
        "candidate_id": evaluation.candidate_id,
        "job_id": evaluation.job_id,
        "status": evaluation.status,
        "match_score": None if failed else evaluation.match_score,
        "recommendation": (
            "EVALUATION_FAILED"
            if failed
            else evaluation.recommendation
        ),
        "summary": (
            FAILED_EVALUATION_PUBLIC_MESSAGE
            if failed
            else (evaluation.summary or "")
        ),
        "strengths": [] if failed else (evaluation.strengths or []),
        "gaps": [] if failed else (evaluation.gaps or []),
        "requirements": (
            []
            if failed
            else (evaluation.requirements or [])
        ),
        "error_message": (
            FAILED_EVALUATION_PUBLIC_MESSAGE
            if failed
            else None
        ),
    }


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
    jobs = crud.list_jobs(db, owner_sub=_user["sub"])
    return [
        {
            "job_id": j.id,
            "id": j.id,
            "title": j.title,
            "description": j.description,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "candidate_count": crud.count_candidates_for_job(db, j.id, owner_sub=_user["sub"]),
        }
        for j in jobs
    ]


@app.post("/api/jobs", status_code=201)
def create_job(
    body: CreateJobRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    job = crud.create_job(
        db,
        title=body.title,
        description=body.description,
        owner_sub=_user["sub"],
    )
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
    job = _require_job(db, job_id, _user["sub"])
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
    delete_candidates: bool = Query(False),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id, _user["sub"])
    success, deleted_count = crud.delete_job(
        db,
        job_id,
        owner_sub=_user["sub"],
        delete_candidates=delete_candidates,
    )
    if not success:
        raise HTTPException(
            status_code=404,
            detail="Vacante no encontrada.",
        )
    if delete_candidates:
        return {
            "detail": "Vacante y candidatos eliminados.",
            "job_id": job_id,
            "delete_candidates": True,
            "deleted_candidates": deleted_count,
        }
    return {
        "detail": "Vacante eliminada.",
        "job_id": job_id,
        "delete_candidates": False,
        "deleted_candidates": 0,
    }


# ============================================================
# CANDIDATES
# ============================================================

@app.get("/api/candidates")
def list_candidates(
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    candidates = crud.list_candidates(db, owner_sub=_user["sub"])
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
    c = _require_candidate(db, candidate_id, _user["sub"])
    return {
        "candidate_id": c.id,
        "id": c.id,
        "name": c.name,
        "email": c.email,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "metadata": c.metadata_,
        "filename": c.metadata_.get("filename") if c.metadata_ else None,
    }


S3_BUCKET = os.getenv("S3_BUCKET", "ai-cv-rag-adrian-2026")
S3_PREFIX = "documents"
KNOWLEDGE_BASE_ID = os.getenv("KNOWLEDGE_BASE_ID", "VUGNMJQAEN")
DATA_SOURCE_ID = os.getenv("DATA_SOURCE_ID", "P8SUL2VFHA")


def _get_bedrock_s3_clients():
    """Get S3 and Bedrock Agent clients using the configured session."""
    from app.evaluation import _bedrock_session
    s3 = _bedrock_session.client("s3", region_name=os.getenv("AWS_REGION", "us-east-2"))
    bedrock_agent = _bedrock_session.client("bedrock-agent", region_name=os.getenv("AWS_REGION", "us-east-2"))
    return s3, bedrock_agent


def index_candidate_document(candidate, file_content: bytes, filename: str) -> dict:
    """Upload CV to S3 with PostgreSQL candidate.id and trigger KB ingestion.

    This is the single source of truth for candidate document indexing.
    Uses candidate.id (PostgreSQL UUID) as the canonical candidate_id.

    Returns dict with ingestion_status and optional error.
    """
    import json as _json

    candidate_id = str(candidate.id)
    s3_key = f"{S3_PREFIX}/cv-{candidate_id}.pdf"
    metadata_key = f"{S3_PREFIX}/cv-{candidate_id}.pdf.metadata.json"

    s3, bedrock_agent = _get_bedrock_s3_clients()

    # 1. Upload CV PDF to S3
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=file_content,
            ContentType="application/pdf",
        )
        logger.info("S3 upload OK: %s", s3_key)
    except Exception as exc:
        logger.error("S3 upload failed for candidate %s: %s", candidate_id, exc)
        return {"status": "UPLOAD_FAILED", "error": str(exc)}

    # 2. Create and upload metadata with canonical candidate_id
    metadata = {
        "metadataAttributes": {
            "candidate_id": {"value": {"type": "STRING", "stringValue": candidate_id}},
            "candidate_name": {"value": {"type": "STRING", "stringValue": candidate.name}},
        }
    }
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=metadata_key,
            Body=_json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("S3 metadata OK: %s", metadata_key)
    except Exception as exc:
        logger.error("S3 metadata failed for candidate %s: %s", candidate_id, exc)
        return {"status": "METADATA_FAILED", "error": str(exc)}

    # 3. Trigger Knowledge Base ingestion
    try:
        response = bedrock_agent.start_ingestion_job(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            dataSourceId=DATA_SOURCE_ID,
        )
        job = response.get("ingestionJob", {})
        ingestion_status = job.get("status") or "STARTING"
        ingestion_job_id = job.get("ingestionJobId")
        logger.info(
            "KB ingestion started: job_id=%s status=%s candidate=%s",
            ingestion_job_id, ingestion_status, candidate_id,
        )
        return {
            "status": ingestion_status,
            "ingestion_job_id": ingestion_job_id,
        }
    except Exception as exc:
        logger.error("KB ingestion failed for candidate %s: %s", candidate_id, exc)
        return {"status": "INGESTION_FAILED", "error": str(exc)}


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
            file_content = await f.read()
            if not file_content:
                errors.append({"original_filename": f.filename, "error": "Empty file"})
                continue

            candidate = crud.create_candidate(
                db,
                name=name,
                metadata={"filename": f.filename},
                owner_sub=_user["sub"],
            )

            indexing = index_candidate_document(candidate, file_content, f.filename)

            results.append({
                "candidate_id": candidate.id,
                "name": candidate.name,
                "original_filename": f.filename,
                "ingestion_status": indexing.get("status", "UNKNOWN"),
                "ingestion_job_id": indexing.get("ingestion_job_id"),
                "error": indexing.get("error"),
            })
        except Exception as exc:
            logger.error("Error processing %s: %s", f.filename, exc, exc_info=True)
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
        deleted, failed = crud.delete_all_candidates(
            db,
            owner_sub=_user["sub"],
        )
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
    _require_candidate(db, candidate_id, _user["sub"])
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
    _require_candidate(db, candidate_id, _user["sub"])
    return {"download_url": None, "detail": "CV storage not configured."}


@app.get("/api/candidates/{candidate_id}/evaluations")
def get_candidate_evaluations(
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_candidate(db, candidate_id, _user["sub"])
    evaluations = crud.get_evaluations_for_candidate(db, candidate_id)
    return {
        "evaluations": [
            _public_evaluation_payload(e)
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
    from app.evaluation import (
        evaluate_candidate as llm_evaluate,
        retrieve_candidate,
    )

    candidate = _require_candidate(db, candidate_id, _user["sub"])
    job = _require_job(db, body.job_id, _user["sub"])

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

        eval_status = llm_result.get("status", "COMPLETED")

        if eval_status == "FAILED":
            evaluation = crud.create_evaluation(
                db,
                candidate_id=candidate_id,
                job_id=body.job_id,
                match_score=0.0,
                recommendation="EVALUATION_FAILED",
                summary=(
                    llm_result.get("summary")
                    or FAILED_EVALUATION_PUBLIC_MESSAGE
                ),
                strengths=[],
                gaps=[],
                requirements=[],
                status="FAILED",
                error_message=(
                    llm_result.get("error_message")
                    or "EVALUATION_FAILED"
                ),
            )
        else:
            match_score = llm_result.get("match_score")
            recommendation = llm_result.get("recommendation")
            summary = str(llm_result.get("summary") or "").strip()
            strengths = llm_result.get("strengths", [])
            gaps = llm_result.get("gaps", [])
            requirements = llm_result.get(
                "requirements",
                [],
            )

            if not isinstance(requirements, list):
                raise ValueError(
                    "INVALID_EVALUATION_REQUIREMENTS"
                )

            if match_score is None:
                raise ValueError("INVALID_EVALUATION_SCORE")

            try:
                numeric_score = float(match_score)
            except (TypeError, ValueError) as exc:
                raise ValueError("INVALID_EVALUATION_SCORE") from exc

            if not 0 <= numeric_score <= 100:
                raise ValueError("INVALID_EVALUATION_SCORE")

            valid_recommendations = {
                "STRONG_MATCH",
                "GOOD_MATCH",
                "PARTIAL_MATCH",
                "LOW_MATCH",
            }

            if recommendation not in valid_recommendations:
                raise ValueError("INVALID_EVALUATION_RECOMMENDATION")

            if len(summary) < crud.MIN_SUMMARY_LENGTH:
                raise ValueError("INVALID_EVALUATION_SUMMARY")

            if not isinstance(strengths, list):
                raise ValueError("INVALID_EVALUATION_STRENGTHS")

            if not isinstance(gaps, list):
                raise ValueError("INVALID_EVALUATION_GAPS")

            evaluation = crud.create_evaluation(
                db,
                candidate_id=candidate_id,
                job_id=body.job_id,
                match_score=numeric_score,
                recommendation=recommendation,
                summary=summary,
                strengths=strengths,
                gaps=gaps,
                requirements=requirements,
                status="COMPLETED",
                error_message=None,
            )

    except Exception as exc:
        logger.error(
            "LLM evaluation failed for candidate %s: %s",
            candidate_id,
            exc,
            exc_info=True,
        )

        evaluation = crud.create_evaluation(
            db,
            candidate_id=candidate_id,
            job_id=body.job_id,
            match_score=0.0,
            recommendation="EVALUATION_FAILED",
            summary=FAILED_EVALUATION_PUBLIC_MESSAGE,
            strengths=[],
            gaps=[],
            status="FAILED",
            error_message=str(exc),
        )

    return _public_evaluation_payload(evaluation)

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
    _require_job(db, job_id, _user["sub"])
    if not body.candidate_ids:
        raise HTTPException(status_code=400, detail="candidate_ids requerido.")
    assigned, skipped = crud.assign_candidates_to_job(
        db,
        job_id,
        body.candidate_ids,
        owner_sub=_user["sub"],
    )
    return {"assigned": assigned, "skipped": skipped}


@app.get("/api/jobs/{job_id}/candidates")
def get_job_candidates(
    job_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id, _user["sub"])
    items, total = crud.list_candidates_for_job(
        db,
        job_id,
        page=page,
        page_size=page_size,
        owner_sub=_user["sub"],
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
    _require_job(db, job_id, _user["sub"])
    _require_candidate(db, candidate_id, _user["sub"])

    evaluation = crud.get_evaluation_for_job_candidate(
        db,
        job_id,
        candidate_id,
    )

    if not evaluation:
        raise HTTPException(
            status_code=404,
            detail="Evaluacion no encontrada.",
        )

    return _public_evaluation_payload(evaluation)

@app.get("/api/jobs/{job_id}/candidates/{candidate_id}/explanation")
def get_candidate_explanation(
    job_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id, _user["sub"])
    _require_candidate(db, candidate_id, _user["sub"])

    evaluation = crud.get_evaluation_for_job_candidate(
        db,
        job_id,
        candidate_id,
    )

    if not evaluation:
        return {
            "status": "PENDING",
            "explanation": "Sin evaluacion.",
            "summary": None,
            "analysis": None,
        }

    payload = _public_evaluation_payload(evaluation)

    return {
        "status": payload["status"],
        "explanation": payload["summary"],
        "summary": payload["summary"],
        "analysis": None,
    }

@app.get("/api/jobs/{job_id}/candidates/{candidate_id}/requirements")
def get_candidate_requirements(
    job_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(
        db,
        job_id,
        _user["sub"],
    )
    _require_candidate(
        db,
        candidate_id,
        _user["sub"],
    )

    evaluation = (
        crud.get_evaluation_for_job_candidate(
            db,
            job_id,
            candidate_id,
        )
    )

    if not evaluation:
        return {"requirements": []}

    # New evaluations preserve the exact LLM
    # requirement-level analysis.
    if evaluation.requirements:
        return {
            "requirements":
                evaluation.requirements
        }

    # Legacy fallback for evaluations created
    # before structured requirements existed.
    requirements = []

    for strength in (
        evaluation.strengths or []
    ):
        requirements.append({
            "requirement": strength,
            "status": "MATCH",
            "evidence": None,
        })

    for gap in (
        evaluation.gaps or []
    ):
        requirements.append({
            "requirement": gap,
            "status": "MISSING",
            "evidence": None,
        })

    return {
        "requirements": requirements
    }


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
    scope: str = Query(
        "assigned",
        pattern=r"^(assigned|all)$",
    ),
    recommendation: str | None = Query(None),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id, _user["sub"])

    if min_score > max_score:
        raise HTTPException(
            status_code=400,
            detail=(
                "min_score no puede ser mayor "
                "que max_score."
            ),
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


@app.post("/api/jobs/{job_id}/ranking/recalculate")
def recalculate_ranking(
    job_id: str,
    mode: str = Query(
        "full",
        pattern=r"^(full|incremental)$",
    ),
    scope: str = Query(
        "assigned",
        pattern=r"^(assigned|all)$",
    ),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id, _user["sub"])

    acquired = acquire_job_lock(db, job_id)

    if not acquired:
        raise HTTPException(
            status_code=409,
            detail=(
                "Otro proceso esta recalculando "
                "el ranking."
            ),
        )

    try:
        from app.evaluation import (
            evaluate_candidate as llm_evaluate,
            retrieve_candidate,
        )

        job = crud.get_job(db, job_id)

        meta = crud.get_ranking_metadata(
            db,
            job_id,
        )

        prev_version = (
            meta.ranking_version
            if meta
            else 0
        ) or 0

        new_version = prev_version + 1

        effective_mode = mode

        if (
            mode == "incremental"
            and (
                not meta
                or not meta.generated_at
            )
        ):
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
            ranking_candidates = (
                crud.list_candidates_for_job(
                    db,
                    job_id,
                    page=1,
                    page_size=100000,
                    owner_sub=_user["sub"],
                )[0]
            )

        evaluated_count = 0
        failed_count = 0
        failures = []

        all_items: list[dict] = []

        for candidate in ranking_candidates:
            evaluation = (
                crud.get_evaluation_for_job_candidate(
                    db,
                    job_id,
                    candidate.id,
                )
            )

            if crud.needs_evaluation(
                evaluation,
                force=(effective_mode == "full"),
            ):
                try:
                    results = retrieve_candidate(
                        candidate_id=candidate.id,
                        question=(
                            job.description
                            or job.title
                        ),
                    )

                    llm_result = llm_evaluate(
                        candidate_id=candidate.id,
                        job_description=(
                            job.description
                            or job.title
                        ),
                        results=results,
                    )

                    eval_status = llm_result.get(
                        "status",
                        "COMPLETED",
                    )

                    if eval_status == "FAILED":
                        evaluation = crud.create_evaluation(
                            db,
                            candidate_id=candidate.id,
                            job_id=job_id,
                            match_score=0.0,
                            recommendation=(
                                llm_result.get(
                                    "recommendation",
                                    "EVALUATION_FAILED",
                                )
                            ),
                            summary=(
                                llm_result.get(
                                    "summary",
                                    "",
                                )
                            ),
                            strengths=[],
                            gaps=[],
                            status="FAILED",
                            error_message=(
                                llm_result.get(
                                    "error_message",
                                    "EVALUATION_FAILED",
                                )
                            ),
                        )

                        failed_count += 1

                        failures.append({
                            "candidate_id": candidate.id,
                            "error": llm_result.get(
                                "error_message",
                                "EVALUATION_FAILED",
                            ),
                        })

                    else:
                        evaluation = crud.create_evaluation(
                            db,
                            candidate_id=candidate.id,
                            job_id=job_id,
                            match_score=llm_result.get(
                                "match_score",
                                0,
                            ),
                            recommendation=(
                                llm_result.get(
                                    "recommendation",
                                    "LOW_MATCH",
                                )
                            ),
                            summary=llm_result.get(
                                "summary",
                                "",
                            ),
                            strengths=llm_result.get(
                                "strengths",
                                [],
                            ),
                            gaps=llm_result.get(
                                "gaps",
                                [],
                            ),
                            requirements=llm_result.get(
                                "requirements",
                                [],
                            ),
                            status="COMPLETED",
                            error_message=None,
                        )

                        evaluated_count += 1

                except Exception as exc:
                    logger.error(
                        "Evaluation failed for "
                        "candidate %s: %s",
                        candidate.id,
                        exc,
                        exc_info=True,
                    )

                    failed_count += 1

                    failures.append({
                        "candidate_id": candidate.id,
                        "error": str(exc),
                    })

                    evaluation = crud.create_evaluation(
                        db,
                        candidate_id=candidate.id,
                        job_id=job_id,
                        match_score=0.0,
                        recommendation=(
                            "EVALUATION_FAILED"
                        ),
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
                score = float(
                    evaluation.match_score
                )
            elif (
                evaluation
                and evaluation.status == "FAILED"
            ):
                effective_status = "FAILED"
                score = 0.0
            else:
                effective_status = "PENDING"
                score = 0.0

            all_items.append({
                "candidate_id": candidate.id,
                "candidate_name": (
                    candidate.name or ""
                ),
                "score": score,
                "status": effective_status,
            })

        status_order = {
            "COMPLETED": 0,
            "FAILED": 1,
            "PENDING": 2,
        }

        # Persist ranking items already ordered:
        # highest percentage first.
        all_items.sort(
            key=lambda item: (
                status_order.get(
                    item["status"],
                    99,
                ),
                -float(item["score"]),
                item["candidate_name"].lower(),
                item["candidate_id"],
            )
        )

        for position, item in enumerate(
            all_items,
            start=1,
        ):
            item["position"] = position

        if all_items:
            crud.insert_ranking_items(
                db,
                ranking_id=ranking.id,
                items=all_items,
            )
        else:
            # Important when changing from a populated
            # scope to an empty one.
            crud.insert_ranking_items(
                db,
                ranking_id=ranking.id,
                items=[],
            )

        return {
            "job_id": job_id,
            "mode": effective_mode,
            "scope": scope,
            "total_candidates": len(
                ranking_candidates
            ),
            "evaluated": evaluated_count,
            "failed": failed_count,
            "failures": failures,
            "ranking_version": new_version,
        }

    finally:
        release_job_lock(
            db,
            job_id,
        )


@app.get("/api/jobs/{job_id}/ranking/latest")
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
