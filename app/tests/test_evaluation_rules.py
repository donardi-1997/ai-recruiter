from app.domains.evaluations.rules import (
    validate_completed_evaluation_result,
)


def _valid_result():
    return {
        "match_score": 90,
        "recommendation": "STRONG_MATCH",
        "summary": (
            "La persona candidata presenta evidencia sólida y suficiente frente a "
            "los requisitos principales de la vacante, con fortalezas técnicas y "
            "experiencia relevante para avanzar a una siguiente etapa."
        ),
        "strengths": ["AWS"],
        "gaps": ["Kubernetes"],
        "requirements": [
            {
                "requirement": "AWS",
                "status": "MATCH",
                "evidence": "Experiencia comprobada con AWS.",
            },
            {
                "requirement": "Kubernetes",
                "status": "MISSING",
                "evidence": None,
            },
        ],
    }


def test_completed_evaluation_rejects_score_recommendation_mismatch():
    result = _valid_result()
    result["recommendation"] = "LOW_MATCH"

    valid, error = validate_completed_evaluation_result(result)

    assert valid is False
    assert error == "INCONSISTENT_EVALUATION_RECOMMENDATION"


def test_completed_evaluation_rejects_boolean_score():
    result = _valid_result()
    result["match_score"] = True
    result["recommendation"] = "LOW_MATCH"

    valid, error = validate_completed_evaluation_result(result)

    assert valid is False
    assert error == "INVALID_EVALUATION_SCORE"


def test_completed_evaluation_rejects_non_text_strengths_and_gaps():
    result = _valid_result()
    result["strengths"] = [{"label": "AWS"}]

    valid, error = validate_completed_evaluation_result(result)

    assert valid is False
    assert error == "INVALID_EVALUATION_STRENGTHS"

    result = _valid_result()
    result["gaps"] = [None]

    valid, error = validate_completed_evaluation_result(result)

    assert valid is False
    assert error == "INVALID_EVALUATION_GAPS"


def test_completed_evaluation_rejects_malformed_requirement_items():
    result = _valid_result()
    result["requirements"] = [
        {
            "requirement": "AWS",
            "status": "UNKNOWN",
            "evidence": "text",
        }
    ]

    valid, error = validate_completed_evaluation_result(result)

    assert valid is False
    assert error == "INVALID_EVALUATION_REQUIREMENTS"
