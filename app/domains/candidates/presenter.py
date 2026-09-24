"""Pure response mapping for the Candidates domain."""

FAILED_EVALUATION_PUBLIC_MESSAGE = (
    "No fue posible completar la evaluación. Intenta nuevamente."
)


def candidate_to_dict(candidate) -> dict:
    metadata = candidate.metadata_
    return {
        "candidate_id": candidate.id,
        "id": candidate.id,
        "name": candidate.name,
        "email": candidate.email,
        "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
        "metadata": metadata,
        "filename": metadata.get("filename") if metadata else None,
        "is_banned": bool(candidate.is_banned),
        "banned_at": candidate.banned_at.isoformat() if candidate.banned_at else None,
        "banned_by_sub": candidate.banned_by_sub,
        "banned_reason": candidate.banned_reason,
    }


def evaluation_to_dict(evaluation) -> dict:
    failed = evaluation.status == "FAILED"
    return {
        "evaluation_id": evaluation.id,
        "candidate_id": evaluation.candidate_id,
        "job_id": evaluation.job_id,
        "status": evaluation.status,
        "match_score": None if failed else evaluation.match_score,
        "recommendation": (
            "EVALUATION_FAILED" if failed else evaluation.recommendation
        ),
        "summary": (
            FAILED_EVALUATION_PUBLIC_MESSAGE
            if failed
            else (evaluation.summary or "")
        ),
        "strengths": [] if failed else (evaluation.strengths or []),
        "gaps": [] if failed else (evaluation.gaps or []),
        "requirements": [] if failed else (evaluation.requirements or []),
        "error_message": FAILED_EVALUATION_PUBLIC_MESSAGE if failed else None,
    }


def evaluation_explanation_to_dict(evaluation) -> dict:
    if evaluation is None:
        return {
            "status": "PENDING",
            "explanation": "Sin evaluacion.",
            "summary": None,
            "analysis": None,
        }

    failed = evaluation.status == "FAILED"
    summary = (
        FAILED_EVALUATION_PUBLIC_MESSAGE
        if failed
        else (evaluation.summary or "")
    )
    return {
        "status": evaluation.status,
        "explanation": summary,
        "summary": summary,
        "analysis": None,
    }


def evaluation_requirements_to_dict(evaluation) -> dict:
    if evaluation is None:
        return {"requirements": []}

    if evaluation.requirements:
        return {"requirements": evaluation.requirements}

    requirements = []
    for strength in evaluation.strengths or []:
        requirements.append(
            {
                "requirement": strength,
                "status": "MATCH",
                "evidence": None,
            }
        )
    for gap in evaluation.gaps or []:
        requirements.append(
            {
                "requirement": gap,
                "status": "MISSING",
                "evidence": None,
            }
        )
    return {"requirements": requirements}



def restriction_event_to_dict(event) -> dict:
    return {
        "id": event.id,
        "candidate_id": event.candidate_id,
        "action": event.action,
        "reason": event.reason,
        "created_by_sub": event.created_by_sub,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }
