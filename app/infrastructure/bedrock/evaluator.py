"""Candidate evaluation using Bedrock LLM.

Contains the canonical evaluation pipeline using Bedrock LLM.
"""

import json
import logging

from langchain_core.prompts import ChatPromptTemplate

from app.infrastructure.bedrock.clients import get_llm
from app.infrastructure.bedrock.parser import invoke_json_prompt
from app.infrastructure.bedrock.prompts import (
    CANDIDATE_EVALUATION_PROMPT,
    REQUIREMENT_EXTRACTION_PROMPT,
)
from app.infrastructure.bedrock.retriever import retrieve_candidate
from app.domains.evaluations.rules import (
    MIN_SUMMARY_LENGTH,
    normalize_requirement,
    recommendation_for_score,
)

logger = logging.getLogger(__name__)


FAILED_EVALUATION_SUMMARY_NO_RESULTS = (
    "No fue posible evaluar al candidato porque "
    "no se encontró información relevante en el Knowledge Base."
)

FAILED_EVALUATION_SUMMARY_NO_REQUIREMENTS = (
    "No se pudieron identificar requisitos explícitos en la descripción de la vacante. "
    "Sin una lista clara de requisitos técnicos o profesionales, no es posible realizar "
    "una evaluación objetiva del perfil del candidato frente a las necesidades del puesto."
)

EVALUATION_FAILED_SUMMARY = (
    "No fue posible completar la evaluación. Intenta nuevamente."
)


def evaluate_candidate(
    candidate_id: str,
    job_description: str,
    results: list,
) -> dict:
    """Evaluate a candidate against a job description using LLM.

    Args:
        candidate_id: Canonical candidate UUID
        job_description: Job description text
        results: Retrieval results from Knowledge Base

    Returns:
        dict with: match_score, recommendation, requirements,
        strengths, gaps, summary, status, error_message (if FAILED)
    """
    # No results -> candidate context not found in KB
    if not results:
        return {
            "match_score": 0,
            "recommendation": "EVALUATION_FAILED",
            "requirements": [],
            "strengths": [],
            "gaps": [],
            "summary": FAILED_EVALUATION_SUMMARY_NO_RESULTS,
            "status": "FAILED",
            "error_message": "CANDIDATE_CONTEXT_NOT_FOUND",
        }

    # Build CV context from retrieval results
    context_parts = []
    for result in results:
        text = result.get("content", {}).get("text", "")
        if text:
            context_parts.append(text)
    context = "\n\n---\n\n".join(context_parts)

    # STEP 1: Extract requirements from job description
    extraction_chain = REQUIREMENT_EXTRACTION_PROMPT | get_llm()
    extraction = invoke_json_prompt(
        extraction_chain,
        {"job_description": job_description, "_retry_instruction": ""},
        "extraer requisitos",
    )

    requirements_from_job = extraction.get("requirements", [])
    if not isinstance(requirements_from_job, list):
        requirements_from_job = []

    # Normalize requirements
    normalized_requirements = []
    seen = set()
    for requirement in requirements_from_job:
        if not isinstance(requirement, str):
            continue
        normalized = normalize_requirement(requirement).strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key not in seen:
            seen.add(key)
            normalized_requirements.append(normalized)
    requirements_from_job = normalized_requirements

    if not requirements_from_job:
        return {
            "match_score": 0,
            "recommendation": "LOW_MATCH",
            "requirements": [],
            "strengths": [],
            "gaps": [],
            "summary": FAILED_EVALUATION_SUMMARY_NO_REQUIREMENTS,
        }

    # STEP 2: Prepare requirements text
    requirements_text = "\n".join(f"- {r}" for r in requirements_from_job)

    # STEP 3: Evaluate requirements against CV
    evaluation_chain = CANDIDATE_EVALUATION_PROMPT | get_llm()
    evaluation = invoke_json_prompt(
        evaluation_chain,
        {"requirements": requirements_text, "context": context, "_retry_instruction": ""},
        "evaluar requisitos contra CV",
    )

    # Normalize evaluation results
    raw_requirements = evaluation.get("requirements", [])
    valid_statuses = {"MATCH", "PARTIAL", "MISSING"}
    evaluated = {}

    for item in raw_requirements:
        if not isinstance(item, dict):
            continue
        requirement = str(item.get("requirement", "")).strip()
        if not requirement:
            continue
        normalized_requirement = normalize_requirement(requirement).strip()
        status = str(item.get("status", "MISSING")).upper().strip()
        if status not in valid_statuses:
            status = "MISSING"
        evidence = item.get("evidence")
        if status == "MISSING":
            evidence = None
        elif evidence is not None:
            evidence = str(evidence).strip()
            words = evidence.split()
            if len(words) > 30:
                evidence = " ".join(words[:30]) + "..."
        key = normalized_requirement.lower().strip()
        evaluated[key] = {
            "requirement": normalized_requirement,
            "status": status,
            "evidence": evidence,
        }

    # Guarantee all requirements are present
    final_requirements = []
    for requirement in requirements_from_job:
        normalized_requirement = normalize_requirement(requirement).strip()
        key = normalized_requirement.lower().strip()
        existing = evaluated.get(key)
        if existing:
            final_requirements.append(
                {
                    "requirement": normalized_requirement,
                    "status": existing.get("status", "MISSING"),
                    "evidence": existing.get("evidence"),
                }
            )
        else:
            final_requirements.append(
                {
                    "requirement": normalized_requirement,
                    "status": "MISSING",
                    "evidence": None,
                }
            )

    # Calculate score
    total = len(final_requirements)
    points = 0
    for requirement in final_requirements:
        status = requirement.get("status", "MISSING")
        if status == "MATCH":
            points += 1
        elif status == "PARTIAL":
            points += 0.5

    match_score = round((points / total) * 100) if total > 0 else 0

    # Recommendation
    recommendation = recommendation_for_score(match_score)

    # Strengths
    strengths = [
        r.get("requirement") for r in final_requirements if r.get("status") == "MATCH"
    ]

    # Gaps
    gaps = [
        r.get("requirement")
        for r in final_requirements
        if r.get("status") in {"PARTIAL", "MISSING"}
    ]

    # Summary
    match_count = sum(1 for r in final_requirements if r["status"] == "MATCH")
    partial_count = sum(1 for r in final_requirements if r["status"] == "PARTIAL")
    missing_count = sum(1 for r in final_requirements if r["status"] == "MISSING")

    # Build a substantial summary (minimum 100 characters)
    parts = []
    parts.append(
        f"El candidato cumple completamente {match_count} de {total} requisitos evaluados"
    )
    if partial_count > 0:
        parts.append(
            f", cumple parcialmente {partial_count} requisito{'s' if partial_count > 1 else ''}"
        )
    if missing_count > 0:
        parts.append(
            f" y no presenta evidencia suficiente para {missing_count} requisito{'s' if missing_count > 1 else ''}"
        )
    parts.append(".")

    if strengths:
        parts.append(
            f" Sus fortalezas principales incluyen: {', '.join(strengths[:3])}."
        )
    if gaps:
        parts.append(
            f" Las áreas de mejora identificadas son: {', '.join(gaps[:3])}."
        )

    summary = "".join(parts)

    # Ensure summary is at least 100 characters
    if len(summary.strip()) < MIN_SUMMARY_LENGTH:
        summary = (
            f"El candidato ha sido evaluado contra {total} requisitos del puesto. "
            f"Se identificaron {match_count} requisitos cumplidos, "
            f"{partial_count} requisitos parcialmente cubiertos "
            f"y {missing_count} requisitos sin evidencia suficiente en el CV. "
            f"Este resultado proporciona una visión general del ajuste del perfil "
            f"del candidato a las necesidades específicas de la vacante."
        )

    return {
        "match_score": match_score,
        "recommendation": recommendation,
        "requirements": final_requirements,
        "strengths": strengths,
        "gaps": gaps,
        "summary": summary,
    }