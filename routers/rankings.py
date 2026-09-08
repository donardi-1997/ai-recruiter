import json

from boto3.dynamodb.conditions import Key, Attr

from fastapi import APIRouter, Depends, HTTPException

from core.auth import get_current_user
from core.aws_clients import candidates_table, evaluations_table
from core.helpers import (
    get_job_record,
    get_job_candidate_ids,
    get_owned_candidate_ids,
    get_ranking_metadata,
    save_ranking_metadata,
    get_new_candidate_ids,
    assign_candidate_to_job,
)
from core.models import (
    CandidateRankingItem,
    JobRankingResponse,
)

router = APIRouter(prefix="/api/jobs", tags=["rankings"])


@router.post("/{job_id}/ranking/recalculate")
def recalculate_job_ranking(
    job_id: str,
    mode: str = "full",
    scope: str = "assigned",
    current_user: dict = Depends(get_current_user),
):
    if mode not in ("full", "incremental"):
        raise HTTPException(
            status_code=400,
            detail="mode debe ser 'full' o 'incremental'.",
        )
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
    owner_id = current_user["sub"]

    if mode == "incremental":
        metadata = get_ranking_metadata(job_id)
        since = metadata.get("ranking_generated_at") if metadata else None
        if since:
            assigned_ids = get_new_candidate_ids(job_id, owner_id, since)
        else:
            assigned_ids = get_job_candidate_ids(job_id, owner_id)
    else:
        assigned_ids = get_job_candidate_ids(job_id, owner_id)

    if scope == "all":
        assigned_ids = get_owned_candidate_ids(owner_id)

    candidates = []
    scan_kwargs = {"FilterExpression": Attr("owner_id").eq(owner_id)}
    while True:
        response = candidates_table.scan(**scan_kwargs)
        candidates.extend(
            c
            for c in response.get("Items", [])
            if c.get("candidate_id") in assigned_ids
        )
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    evaluated = 0
    failures = []
    for candidate in candidates:
        try:
            from core.llm import evaluate_and_save

            evaluate_and_save(
                candidate_id=candidate["candidate_id"],
                job_id=job_id,
                current_user=current_user,
            )
            evaluated += 1
        except ValueError as error:
            failures.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "error": str(error),
                }
            )
        except Exception as error:
            failures.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "error": str(error),
                }
            )

    prev_metadata = get_ranking_metadata(job_id)
    prev_version = (
        prev_metadata.get("ranking_version", 0) if prev_metadata else 0
    )
    new_version = prev_version + 1
    save_ranking_metadata(job_id, new_version)

    return {
        "job_id": job_id,
        "mode": mode,
        "total_candidates": len(candidates),
        "evaluated": evaluated,
        "failed": len(failures),
        "failures": failures,
        "ranking_version": new_version,
    }


@router.get("/{job_id}/ranking", response_model=JobRankingResponse)
def get_job_ranking(
    job_id: str,
    scope: str = "assigned",
    min_score: int = 0,
    max_score: int = 100,
    recommendation: str | None = None,
    limit: int | None = None,
    page: int = 1,
    page_size: int = 10,
    current_user: dict = Depends(get_current_user),
):
    try:
        if min_score < 0 or min_score > 100:
            raise HTTPException(
                status_code=400,
                detail="min_score debe estar entre 0 y 100.",
            )
        if max_score < 0 or max_score > 100:
            raise HTTPException(
                status_code=400,
                detail="max_score debe estar entre 0 y 100.",
            )
        if min_score > max_score:
            raise HTTPException(
                status_code=400,
                detail="min_score no puede ser mayor que max_score.",
            )
        if limit is not None and limit <= 0:
            raise HTTPException(
                status_code=400,
                detail="limit debe ser mayor que 0.",
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
        if recommendation:
            recommendation = recommendation.upper()
            allowed = {
                "STRONG_MATCH",
                "GOOD_MATCH",
                "PARTIAL_MATCH",
                "LOW_MATCH",
                "PENDING",
            }
            if recommendation not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "recommendation debe ser "
                        "STRONG_MATCH, GOOD_MATCH, "
                        "PARTIAL_MATCH, LOW_MATCH o PENDING."
                    ),
                )
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
        owner_id = current_user["sub"]
        assigned_ids = get_job_candidate_ids(job_id, owner_id)
        if scope == "all":
            assigned_ids = get_owned_candidate_ids(owner_id)
        if not assigned_ids:
            legacy_evaluations = evaluations_table.query(
                KeyConditionExpression=Key("job_id").eq(job_id)
            ).get("Items", [])
            for evaluation in legacy_evaluations:
                cid = evaluation.get("candidate_id")
                if evaluation.get("owner_id") == owner_id and cid:
                    assign_candidate_to_job(job_id, cid, owner_id)
                    assigned_ids.add(cid)

        all_candidates = []
        candidates_response = candidates_table.scan(
            FilterExpression=Attr("owner_id").eq(owner_id)
        )
        all_candidates.extend(
            c
            for c in candidates_response.get("Items", [])
            if c.get("candidate_id") in assigned_ids
        )
        while candidates_response.get("LastEvaluatedKey"):
            candidates_response = candidates_table.scan(
                FilterExpression=Attr("owner_id").eq(owner_id),
                ExclusiveStartKey=candidates_response["LastEvaluatedKey"],
            )
            all_candidates.extend(
                c
                for c in candidates_response.get("Items", [])
                if c.get("candidate_id") in assigned_ids
            )

        evaluations = []
        evaluations_response = evaluations_table.query(
            KeyConditionExpression=Key("job_id").eq(job_id)
        )
        evaluations.extend(evaluations_response.get("Items", []))
        while evaluations_response.get("LastEvaluatedKey"):
            evaluations_response = evaluations_table.query(
                KeyConditionExpression=Key("job_id").eq(job_id),
                ExclusiveStartKey=evaluations_response["LastEvaluatedKey"],
            )
            evaluations.extend(evaluations_response.get("Items", []))

        evaluations_by_candidate = {}
        for evaluation in evaluations:
            cid = evaluation.get("candidate_id")
            if cid:
                evaluations_by_candidate[cid] = evaluation

        candidates = []
        for candidate in all_candidates:
            cid = candidate.get("candidate_id")
            if not cid:
                continue
            evaluation = evaluations_by_candidate.get(cid)
            if not evaluation:
                if recommendation == "PENDING":
                    candidates.append(
                        {
                            "candidate_id": cid,
                            "candidate_name": candidate.get(
                                "name", "Unknown"
                            ),
                            "match_score": 0,
                            "recommendation": "PENDING",
                            "strengths": [],
                            "gaps": [],
                        }
                    )
                continue
            try:
                match_score = int(evaluation.get("match_score", 0))
            except Exception:
                match_score = 0
            match_score = max(0, min(100, match_score))
            eval_recommendation = evaluation.get(
                "recommendation", "LOW_MATCH"
            )
            if not eval_recommendation:
                eval_recommendation = "LOW_MATCH"
            eval_recommendation = str(eval_recommendation).upper()
            if match_score < min_score:
                continue
            if match_score > max_score:
                continue
            if (
                recommendation
                and recommendation != "PENDING"
                and eval_recommendation != recommendation
            ):
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
            candidates.append(
                {
                    "candidate_id": cid,
                    "candidate_name": candidate.get(
                        "name",
                        evaluation.get("candidate_name", "Unknown"),
                    ),
                    "match_score": match_score,
                    "recommendation": eval_recommendation,
                    "status": evaluation.get("status", "COMPLETED"),
                    "strengths": strengths,
                    "gaps": gaps,
                }
            )

        candidates.sort(
            key=lambda c: (c["match_score"], c["candidate_name"].lower()),
            reverse=True,
        )
        if limit is not None:
            candidates = candidates[:limit]
        total = len(candidates)
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        start = (page - 1) * page_size
        end = start + page_size
        paginated_candidates = candidates[start:end]
        ranked_candidates = []
        for index, candidate in enumerate(
            paginated_candidates, start=start + 1
        ):
            ranked_candidates.append(
                CandidateRankingItem(
                    rank=index,
                    candidate_id=candidate["candidate_id"],
                    candidate_name=candidate["candidate_name"],
                    match_score=candidate["match_score"],
                    recommendation=candidate["recommendation"],
                    status=candidate.get("status", "COMPLETED"),
                    strengths=candidate["strengths"],
                    gaps=candidate["gaps"],
                )
            )
        ranking_metadata = get_ranking_metadata(job_id)
        return JobRankingResponse(
            job_id=job_id,
            job_title=job.get("title", ""),
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            pending_candidates=max(
                0, len(all_candidates) - len(evaluations_by_candidate)
            ),
            ranking_generated_at=(
                ranking_metadata.get("ranking_generated_at")
                if ranking_metadata
                else None
            ),
            ranking_version=(
                ranking_metadata.get("ranking_version")
                if ranking_metadata
                else None
            ),
            candidates=ranked_candidates,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



