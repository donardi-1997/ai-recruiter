"""Evaluation presenter — public serialization of Evaluation objects.

Converts internal Evaluation models to public API payloads,
sanitizing technical error details.
"""

FAILED_EVALUATION_PUBLIC_MESSAGE = (
    "No fue posible completar la evaluación. Intenta nuevamente."
)


def public_evaluation_payload(evaluation) -> dict:
    """Serialize an Evaluation without exposing technical failure details.

    FAILED evaluations return sanitized public messages.
    COMPLETED evaluations return full details.
    """
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