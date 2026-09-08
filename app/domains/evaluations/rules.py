"""Evaluation domain rules and validation.

Canonical definitions for evaluation validation rules.
"""

VALID_RECOMMENDATIONS = {
    "STRONG_MATCH",
    "GOOD_MATCH",
    "PARTIAL_MATCH",
    "LOW_MATCH",
    "EVALUATION_FAILED",
    "PENDING",
}

MIN_SUMMARY_LENGTH = 100

PUBLIC_RECOMMENDATIONS = {
    "STRONG_MATCH",
    "GOOD_MATCH",
    "PARTIAL_MATCH",
    "LOW_MATCH",
}


def is_valid_match_score(score: float | None) -> bool:
    """Check if match_score is a valid 0-100 numeric value."""
    if score is None:
        return False
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        return False
    return 0 <= numeric <= 100


def is_valid_recommendation(recommendation: str | None) -> bool:
    """Check if recommendation is a valid public recommendation."""
    if not recommendation:
        return False
    return recommendation in PUBLIC_RECOMMENDATIONS


def validate_completed_evaluation_result(result: dict) -> tuple[bool, str | None]:
    """Validate a completed LLM evaluation result.

    Returns (is_valid, error_message).
    If invalid, error_message explains why.
    """
    # match_score
    match_score = result.get("match_score")
    if not is_valid_match_score(match_score):
        return False, "INVALID_EVALUATION_SCORE"

    # recommendation
    recommendation = result.get("recommendation")
    if not is_valid_recommendation(recommendation):
        return False, "INVALID_EVALUATION_RECOMMENDATION"

    # summary
    summary = str(result.get("summary") or "").strip()
    if len(summary) < MIN_SUMMARY_LENGTH:
        return False, "INVALID_EVALUATION_SUMMARY"

    # strengths
    strengths = result.get("strengths")
    if not isinstance(strengths, list):
        return False, "INVALID_EVALUATION_STRENGTHS"

    # gaps
    gaps = result.get("gaps")
    if not isinstance(gaps, list):
        return False, "INVALID_EVALUATION_GAPS"

    # requirements
    requirements = result.get("requirements")
    if not isinstance(requirements, list):
        return False, "INVALID_EVALUATION_REQUIREMENTS"

    return True, None


def normalize_completed_evaluation_result(result: dict) -> dict:
    """Normalize a validated completed evaluation result for persistence.

    Assumes the result has already passed validate_completed_evaluation_result.
    Returns a dict with normalized values ready for repository persistence.
    """
    match_score = float(result.get("match_score"))
    recommendation = result.get("recommendation")
    summary = str(result.get("summary") or "").strip()
    strengths = result.get("strengths", [])
    gaps = result.get("gaps", [])
    requirements = result.get("requirements", [])

    return {
        "match_score": match_score,
        "recommendation": recommendation,
        "summary": summary,
        "strengths": strengths,
        "gaps": gaps,
        "requirements": requirements,
    }