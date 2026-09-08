import json

from boto3.dynamodb.conditions import Key, Attr

from fastapi import APIRouter, Depends, HTTPException

from core.auth import get_current_user
from core.aws_clients import evaluations_table, candidates_table
from core.helpers import (
    get_job_record,
    get_candidate_record,
)
from core.models import (
    CandidateJobEvaluationResponse,
    CandidateComparisonItem,
    CandidateComparisonResponse,
    CandidateRequirementItem,
    CandidateRequirementsResponse,
)

router = APIRouter(tags=["evaluations"])


@router.get(
    "/api/jobs/{job_id}/candidates/{candidate_id}",
    response_model=CandidateJobEvaluationResponse,
)
def get_candidate_job_evaluation(
    job_id: str,
    candidate_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        job = get_job_record(job_id)
        if not job:
            raise HTTPException(
                status_code=404, detail="Vacante no encontrada."
            )
        if job.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para acceder a esta vacante.",
            )
        candidate = get_candidate_record(candidate_id)
        if not candidate:
            raise HTTPException(
                status_code=404, detail="Candidato no encontrado."
            )
        if candidate.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso sobre este candidato.",
            )
        response = evaluations_table.get_item(
            Key={"job_id": job_id, "candidate_id": candidate_id}
        )
        evaluation = response.get("Item")
        if not evaluation:
            raise HTTPException(
                status_code=404,
                detail=(
                    "El candidato todav\u00eda no ha sido "
                    "evaluado para esta vacante."
                ),
            )
        requirements_raw = evaluation.get("requirements", "[]")
        try:
            requirements = json.loads(requirements_raw)
        except Exception:
            requirements = []
        if not isinstance(requirements, list):
            requirements = []
        strengths_raw = evaluation.get("strengths", "[]")
        try:
            strengths = json.loads(strengths_raw)
        except Exception:
            strengths = []
        if not isinstance(strengths, list):
            strengths = []
        gaps_raw = evaluation.get("gaps", "[]")
        try:
            gaps = json.loads(gaps_raw)
        except Exception:
            gaps = []
        if not isinstance(gaps, list):
            gaps = []
        return CandidateJobEvaluationResponse(
            job_id=job_id,
            candidate_id=candidate_id,
            candidate_name=candidate.get("name", "Unknown"),
            candidate_filename=candidate.get("filename", ""),
            match_score=int(evaluation.get("match_score", 0)),
            recommendation=evaluation.get("recommendation", "LOW_MATCH"),
            requirements=requirements,
            strengths=strengths,
            gaps=gaps,
            summary=evaluation.get("summary", ""),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/api/jobs/{job_id}/candidates/{candidate_id}/explanation",
)
def get_candidate_explanation(
    job_id: str,
    candidate_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        job = get_job_record(job_id)
        if not job:
            raise HTTPException(
                status_code=404, detail="Vacante no encontrada."
            )
        if job.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para acceder a esta vacante.",
            )
        candidate = get_candidate_record(candidate_id)
        if not candidate:
            raise HTTPException(
                status_code=404, detail="Candidato no encontrado."
            )
        if candidate.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso sobre este candidato.",
            )
        response = evaluations_table.get_item(
            Key={"job_id": job_id, "candidate_id": candidate_id}
        )
        evaluation = response.get("Item")
        if not evaluation:
            raise HTTPException(
                status_code=404,
                detail=(
                    "El candidato todav\u00eda no ha sido "
                    "evaluado para esta vacante."
                ),
            )
        requirements = evaluation.get("requirements", [])
        if isinstance(requirements, str):
            try:
                requirements = json.loads(requirements)
            except Exception:
                requirements = []
        strengths = evaluation.get("strengths", [])
        if isinstance(strengths, str):
            try:
                strengths = json.loads(strengths)
            except Exception:
                strengths = []
        gaps = evaluation.get("gaps", [])
        if isinstance(gaps, str):
            try:
                gaps = json.loads(gaps)
            except Exception:
                gaps = []
        matched_requirements = []
        partial_requirements = []
        missing_requirements = []
        for requirement in requirements:
            status = requirement.get("status", "MISSING")
            if status == "MATCH":
                matched_requirements.append(requirement)
            elif status == "PARTIAL":
                partial_requirements.append(requirement)
            else:
                missing_requirements.append(requirement)
        match_score = int(evaluation.get("match_score", 0))
        recommendation = evaluation.get("recommendation", "LOW_MATCH")
        total_requirements = len(requirements)
        matched_count = len(matched_requirements)
        partial_count = len(partial_requirements)
        missing_count = len(missing_requirements)
        explanation = (
            f"El candidato "
            f"{candidate.get('name', 'Unknown')} "
            f"obtuvo un match score de "
            f"{match_score}/100 y fue clasificado como "
            f"{recommendation}. "
            f"Cumple completamente "
            f"{matched_count} de "
            f"{total_requirements} requisitos, "
            f"cumple parcialmente "
            f"{partial_count} y no presenta evidencia "
            f"expl\u00edcita para "
            f"{missing_count}."
        )
        return {
            "job_id": job_id,
            "job_title": job.get("title", "Unknown"),
            "candidate_id": candidate_id,
            "candidate_name": candidate.get("name", "Unknown"),
            "match_score": match_score,
            "recommendation": recommendation,
            "explanation": explanation,
            "matched_requirements": matched_requirements,
            "partial_requirements": partial_requirements,
            "missing_requirements": missing_requirements,
            "key_strengths": strengths,
            "main_gaps": gaps,
            "summary": evaluation.get("summary", ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/api/jobs/{job_id}/candidates/{candidate_id}/requirements",
    response_model=CandidateRequirementsResponse,
)
def get_candidate_requirements(
    job_id: str,
    candidate_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        job = get_job_record(job_id)
        if not job:
            raise HTTPException(
                status_code=404, detail="Vacante no encontrada."
            )
        if job.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para acceder a esta vacante.",
            )
        candidate = get_candidate_record(candidate_id)
        if not candidate:
            raise HTTPException(
                status_code=404, detail="Candidato no encontrado."
            )
        if candidate.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso sobre este candidato.",
            )
        response = evaluations_table.get_item(
            Key={"job_id": job_id, "candidate_id": candidate_id}
        )
        evaluation = response.get("Item")
        if not evaluation:
            raise HTTPException(
                status_code=404,
                detail=(
                    "El candidato todav\u00eda no ha sido "
                    "evaluado para esta vacante."
                ),
            )
        requirements_raw = evaluation.get("requirements", "[]")
        try:
            requirements = (
                json.loads(requirements_raw)
                if isinstance(requirements_raw, str)
                else requirements_raw
            )
        except Exception:
            requirements = []
        normalized_requirements = []
        for requirement in requirements:
            normalized_requirements.append(
                CandidateRequirementItem(
                    requirement=requirement.get("requirement", ""),
                    status=requirement.get("status", "MISSING"),
                    evidence=requirement.get("evidence"),
                )
            )
        return CandidateRequirementsResponse(
            job_id=job_id,
            job_title=job["title"],
            candidate_id=candidate_id,
            candidate_name=candidate.get("name", "Unknown"),
            match_score=int(evaluation.get("match_score", 0)),
            recommendation=evaluation.get("recommendation", "LOW_MATCH"),
            requirements=normalized_requirements,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/api/jobs/{job_id}/compare",
    response_model=CandidateComparisonResponse,
)
def compare_candidates(
    job_id: str,
    candidate_ids: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        job = get_job_record(job_id)
        if not job:
            raise HTTPException(
                status_code=404, detail="Vacante no encontrada."
            )
        if job.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para acceder a esta vacante.",
            )
        ids = [
            cid.strip() for cid in candidate_ids.split(",") if cid.strip()
        ]
        if not ids:
            raise HTTPException(
                status_code=400,
                detail="Debe proporcionar al menos un candidate_id.",
            )
        if len(ids) > 5:
            raise HTTPException(
                status_code=400,
                detail="M\u00e1ximo 5 candidatos por comparaci\u00f3n.",
            )
        candidates_response = candidates_table.scan(
            FilterExpression=Attr("owner_id").eq(current_user["sub"])
        )
        all_candidates = candidates_response.get("Items", [])
        candidates_by_id = {
            c.get("candidate_id"): c
            for c in all_candidates
            if c.get("candidate_id")
        }
        evaluations_response = evaluations_table.query(
            KeyConditionExpression=Key("job_id").eq(job_id)
        )
        evaluations = evaluations_response.get("Items", [])
        evaluations_by_candidate = {}
        for evaluation in evaluations:
            cid = evaluation.get("candidate_id")
            if cid:
                evaluations_by_candidate[cid] = evaluation
        candidates = []
        for cid in ids:
            candidate = candidates_by_id.get(cid)
            if not candidate:
                continue
            evaluation = evaluations_by_candidate.get(cid)
            if not evaluation:
                continue
            strengths_raw = evaluation.get("strengths", [])
            if isinstance(strengths_raw, str):
                try:
                    strengths = json.loads(strengths_raw)
                except Exception:
                    strengths = []
            else:
                strengths = strengths_raw
            if not isinstance(strengths, list):
                strengths = []
            gaps_raw = evaluation.get("gaps", [])
            if isinstance(gaps_raw, str):
                try:
                    gaps = json.loads(gaps_raw)
                except Exception:
                    gaps = []
            else:
                gaps = gaps_raw
            if not isinstance(gaps, list):
                gaps = []
            try:
                match_score = int(evaluation.get("match_score", 0))
            except (TypeError, ValueError):
                match_score = 0
            recommendation = evaluation.get("recommendation", "LOW_MATCH")
            if not recommendation:
                recommendation = "LOW_MATCH"
            recommendation = str(recommendation).upper()
            candidates.append(
                CandidateComparisonItem(
                    candidate_id=cid,
                    candidate_name=candidate.get("name", "Unknown"),
                    match_score=match_score,
                    recommendation=recommendation,
                    strengths=strengths,
                    gaps=gaps,
                )
            )
        if not candidates:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No se encontraron evaluaciones "
                    "para los candidatos indicados."
                ),
            )
        candidates.sort(key=lambda c: c.match_score, reverse=True)
        winner = candidates[0]
        return CandidateComparisonResponse(
            job_id=job_id,
            job_title=job.get("title", ""),
            candidates=candidates,
            winner=winner,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
