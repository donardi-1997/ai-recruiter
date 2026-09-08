import json
import uuid

from boto3.dynamodb.conditions import Key, Attr

from fastapi import APIRouter, Depends, HTTPException

from core.auth import get_current_user
from core.aws_clients import (
    jobs_table,
    candidates_table,
    evaluations_table,
)
from core.helpers import (
    get_job_record,
    get_candidate_record,
    save_job_record,
    get_job_candidate_ids,
    assign_candidate_to_job,
)
from core.models import (
    CreateJobRequest,
    JobResponse,
    AssignCandidatesRequest,
    JobSummaryTopCandidate,
    JobSummaryResponse,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse)
def create_job(
    request: CreateJobRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "title": request.title.strip(),
            "description": request.description.strip(),
            "owner_id": current_user["sub"],
        }
        save_job_record(job)
        return JobResponse(**job)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
def list_jobs(current_user: dict = Depends(get_current_user)):
    try:
        response = jobs_table.scan()
        jobs = response.get("Items", [])
        owner_id = current_user["sub"]
        user_jobs = [job for job in jobs if job.get("owner_id") == owner_id]
        for job in user_jobs:
            assigned_ids = get_job_candidate_ids(job["job_id"], owner_id)
            job["candidate_count"] = len(assigned_ids)
        return {"jobs": user_jobs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{job_id}")
def get_job(job_id: str, current_user: dict = Depends(get_current_user)):
    job = get_job_record(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")
    if job.get("owner_id") != current_user["sub"]:
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para acceder a esta vacante.",
        )
    return job


@router.delete("/{job_id}")
def delete_job(
    job_id: str, current_user: dict = Depends(get_current_user)
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
        evaluations = evaluations_table.query(
            KeyConditionExpression=Key("job_id").eq(job_id)
        )
        for evaluation in evaluations.get("Items", []):
            evaluations_table.delete_item(
                Key={
                    "job_id": job_id,
                    "candidate_id": evaluation["candidate_id"],
                }
            )
        jobs_table.delete_item(Key={"job_id": job_id})
        return {
            "message": "Vacante eliminada correctamente.",
            "job_id": job_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{job_id}/candidates")
def assign_candidates_to_job(
    job_id: str,
    request: AssignCandidatesRequest,
    current_user: dict = Depends(get_current_user),
):
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
    assigned = 0
    for candidate_id in dict.fromkeys(request.candidate_ids):
        candidate = get_candidate_record(candidate_id)
        if not candidate:
            continue
        if candidate.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso sobre uno de los candidatos.",
            )
        assign_candidate_to_job(job_id, candidate_id, current_user["sub"])
        assigned += 1
    return {
        "job_id": job_id,
        "assigned": assigned,
        "candidate_ids": list(dict.fromkeys(request.candidate_ids)),
    }


@router.delete("/{job_id}/candidates/{candidate_id}")
def unassign_candidate_from_job(
    job_id: str,
    candidate_id: str,
    current_user: dict = Depends(get_current_user),
):
    from core.aws_clients import job_candidates_table

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
    if not candidate or candidate.get("owner_id") != current_user["sub"]:
        raise HTTPException(
            status_code=404, detail="Candidato no encontrado."
        )
    job_candidates_table.delete_item(
        Key={"job_id": job_id, "candidate_id": candidate_id}
    )
    return {"job_id": job_id, "candidate_id": candidate_id, "unassigned": True}


@router.get("/{job_id}/evaluations")
def get_job_evaluations(
    job_id: str, current_user: dict = Depends(get_current_user)
):
    try:
        from core.helpers import parse_json_field

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
        response = evaluations_table.query(
            KeyConditionExpression=Key("job_id").eq(job_id)
        )
        evaluations = response.get("Items", [])
        for item in evaluations:
            item["requirements"] = parse_json_field(
                item.get("requirements", [])
            )
            item["strengths"] = parse_json_field(item.get("strengths", []))
            item["gaps"] = parse_json_field(item.get("gaps", []))
        evaluations.sort(
            key=lambda x: int(x.get("match_score", 0)), reverse=True
        )
        return {
            "job_id": job_id,
            "job_title": job.get("title", ""),
            "total": len(evaluations),
            "evaluations": evaluations,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{job_id}/summary", response_model=JobSummaryResponse)
def get_job_summary(
    job_id: str, current_user: dict = Depends(get_current_user)
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
        response = evaluations_table.query(
            KeyConditionExpression=Key("job_id").eq(job_id)
        )
        evaluations = response.get("Items", [])
        evaluated_candidates = 0
        failed_candidates = 0
        pending_candidates = 0
        strong_matches = 0
        partial_matches = 0
        low_matches = 0
        scores = []
        top_evaluation = None
        for evaluation in evaluations:
            status = evaluation.get("status", "COMPLETED")
            if status == "COMPLETED":
                evaluated_candidates += 1
            elif status == "FAILED":
                failed_candidates += 1
            else:
                pending_candidates += 1
            if status != "COMPLETED":
                continue
            match_score = int(evaluation.get("match_score", 0))
            scores.append(match_score)
            recommendation = evaluation.get("recommendation", "LOW_MATCH")
            if recommendation == "STRONG_MATCH":
                strong_matches += 1
            elif recommendation == "PARTIAL_MATCH":
                partial_matches += 1
            else:
                low_matches += 1
            if top_evaluation is None or match_score > int(
                top_evaluation.get("match_score", 0)
            ):
                top_evaluation = evaluation
        average_score = round(sum(scores) / len(scores), 1) if scores else 0.0
        top_candidate = None
        if top_evaluation:
            top_candidate_id = top_evaluation["candidate_id"]
            candidate = get_candidate_record(top_candidate_id)
            top_candidate = JobSummaryTopCandidate(
                candidate_id=top_candidate_id,
                candidate_name=candidate.get("name", "Unknown"),
                match_score=int(top_evaluation.get("match_score", 0)),
                recommendation=top_evaluation.get("recommendation", "LOW_MATCH"),
            )
        owner_candidates = []
        candidates_response = candidates_table.scan(
            FilterExpression=Attr("owner_id").eq(current_user["sub"])
        )
        owner_candidates.extend(candidates_response.get("Items", []))
        while candidates_response.get("LastEvaluatedKey"):
            candidates_response = candidates_table.scan(
                FilterExpression=Attr("owner_id").eq(current_user["sub"]),
                ExclusiveStartKey=candidates_response["LastEvaluatedKey"],
            )
            owner_candidates.extend(candidates_response.get("Items", []))
        evaluated_ids = {
            item.get("candidate_id")
            for item in evaluations
            if item.get("status", "COMPLETED") == "COMPLETED"
        }
        total_candidates = len(owner_candidates)
        pending_candidates = max(0, total_candidates - len(evaluated_ids))
        return JobSummaryResponse(
            job_id=job_id,
            job_title=job["title"],
            total_candidates=total_candidates,
            evaluated_candidates=evaluated_candidates,
            pending_candidates=pending_candidates,
            failed_candidates=failed_candidates,
            strong_matches=strong_matches,
            partial_matches=partial_matches,
            low_matches=low_matches,
            average_score=average_score,
            top_candidate=top_candidate,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{job_id}/candidates")
def get_job_candidates(
    job_id: str,
    min_score: int = 0,
    recommendation: str | None = None,
    page: int = 1,
    page_size: int = 10,
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
        if page < 1:
            raise HTTPException(
                status_code=400,
                detail="page debe ser mayor o igual a 1.",
            )
        if page_size < 1 or page_size > 100:
            raise HTTPException(
                status_code=400,
                detail="page_size debe estar entre 1 y 100.",
            )
        if min_score < 0 or min_score > 100:
            raise HTTPException(
                status_code=400,
                detail="min_score debe estar entre 0 y 100.",
            )
        response = evaluations_table.query(
            KeyConditionExpression=Key("job_id").eq(job_id)
        )
        evaluations = response.get("Items", [])
        candidates = []
        for evaluation in evaluations:
            match_score = int(evaluation.get("match_score", 0))
            current_recommendation = evaluation.get(
                "recommendation", "LOW_MATCH"
            )
            if match_score < min_score:
                continue
            if (
                recommendation
                and current_recommendation != recommendation
            ):
                continue
            candidate_id = evaluation.get("candidate_id")
            if not candidate_id:
                continue
            candidate = get_candidate_record(candidate_id)
            if not candidate:
                continue
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
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "candidate_name": candidate.get("name", "Unknown"),
                    "match_score": match_score,
                    "recommendation": current_recommendation,
                    "strengths": strengths,
                    "gaps": gaps,
                }
            )
        candidates.sort(
            key=lambda c: (c["match_score"], c["candidate_name"]),
            reverse=True,
        )
        total = len(candidates)
        total_pages = (total + page_size - 1) // page_size
        start = (page - 1) * page_size
        end = start + page_size
        paginated_candidates = candidates[start:end]
        for index, candidate in enumerate(
            paginated_candidates, start=start + 1
        ):
            candidate["rank"] = index
        return {
            "job_id": job_id,
            "job_title": job["title"],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "candidates": paginated_candidates,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
