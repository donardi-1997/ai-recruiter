"""Shared evaluation logic for AI Recruiter.

Contains the Bedrock retrieval and LLM evaluation functions
used by both the DynamoDB and PostgreSQL backends.
"""

import json
import logging
import os

import boto3
from langchain_aws import ChatBedrock
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION
# ============================================================

AWS_REGION = os.getenv("AWS_REGION", "us-east-2")
KNOWLEDGE_BASE_ID = os.getenv("KNOWLEDGE_BASE_ID", "VUGNMJQAEN")
BEDROCK_AWS_PROFILE = os.getenv("BEDROCK_AWS_PROFILE")
NUMBER_OF_RESULTS = 50

# ============================================================
# AWS SESSION (uses IAM Roles Anywhere profile for Bedrock)
# ============================================================

def _get_bedrock_session():
    """Create a boto3 session for Bedrock.

    If BEDROCK_AWS_PROFILE is set, use that profile (IAM Roles Anywhere).
    If not set, use the default credential chain.
    """
    if BEDROCK_AWS_PROFILE:
        logger.info(
            "Using configured Bedrock AWS profile: %s",
            BEDROCK_AWS_PROFILE,
        )
        return boto3.Session(profile_name=BEDROCK_AWS_PROFILE)

    logger.info("Using default AWS credential chain")
    return boto3.Session()


_bedrock_session = _get_bedrock_session()

bedrock_agent_runtime = _bedrock_session.client(
    "bedrock-agent-runtime",
    region_name=AWS_REGION,
)

# ============================================================
# LLM
# ============================================================

llm = ChatBedrock(
    client=_bedrock_session.client("bedrock-runtime", region_name=AWS_REGION),
    model_id="amazon.nova-lite-v1:0",
    region_name=AWS_REGION,
    model_kwargs={"temperature": 0},
)


# ============================================================
# JSON CLEANER
# ============================================================
def clean_json(content: str) -> str:
    if not content:
        raise ValueError("El modelo devolvió una respuesta vacía.")
    content = str(content).strip()
    if content.startswith("```json"):
        content = content[7:].strip()
    elif content.startswith("```"):
        content = content[3:].strip()
    if content.endswith("```"):
        content = content[:-3].strip()
    start = content.find("{")
    if start == -1:
        raise ValueError(
            f"No se encontró un objeto JSON en la respuesta: {content}"
        )
    end = content.rfind("}")
    if end == -1 or end < start:
        raise ValueError(f"El JSON está incompleto: {content}")
    return content[start : end + 1].strip()


# ============================================================
# INVOKE JSON PROMPT
# ============================================================
def invoke_json_prompt(chain, payload: dict, description: str):
    response = chain.invoke(payload)
    raw_content = response.content
    cleaned_content = clean_json(raw_content)
    try:
        return json.loads(cleaned_content)
    except json.JSONDecodeError as first_error:
        logger.error("JSON inválido en %s: %s", description, first_error)
        logger.error("Respuesta recibida: %s", raw_content)
    retry_payload = dict(payload)
    retry_payload["_retry_instruction"] = """
La respuesta anterior NO fue JSON válido.
Debes responder nuevamente.
REGLAS ABSOLUTAS:
- Devuelve únicamente JSON.
- No utilices Markdown.
- No utilices ```json.
- No utilices ``` .
- No escribas explicaciones.
- No escribas texto antes del JSON.
- No escribas texto después del JSON.
- Todos los strings deben utilizar comillas dobles.
- No agregues propiedades adicionales.
"""
    retry_response = chain.invoke(retry_payload)
    retry_raw_content = retry_response.content
    retry_cleaned_content = clean_json(retry_raw_content)
    try:
        return json.loads(retry_cleaned_content)
    except json.JSONDecodeError as second_error:
        raise ValueError(
            f"El modelo no devolvió JSON válido al {description}. "
            f"Primer error: {first_error}. "
            f"Segundo error: {second_error}. "
            f"Respuesta: {retry_cleaned_content}"
        ) from second_error


# ============================================================
# RETRIEVE CANDIDATE FROM BEDROCK KNOWLEDGE BASE
# ============================================================
def retrieve_candidate(candidate_id: str, question: str) -> list:
    """Retrieve CV context from Bedrock Knowledge Base for a candidate."""
    response = bedrock_agent_runtime.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={"text": question},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": NUMBER_OF_RESULTS,
                "filter": {
                    "equals": {
                        "key": "candidate_id",
                        "value": candidate_id,
                    }
                },
            }
        },
    )
    results = response.get("retrievalResults", [])
    logger.info("RETRIEVE candidate_id=%s results=%d", candidate_id, len(results))
    return results


# ============================================================
# EVALUATE CANDIDATE AGAINST JOB DESCRIPTION
# ============================================================
def evaluate_candidate(
    candidate_id: str,
    job_description: str,
    results: list,
) -> dict:
    """Evaluate a candidate against a job description using LLM.

    Returns a dict with: match_score, recommendation, requirements,
    strengths, gaps, summary.
    """
    # No results -> candidate context not found in KB
    if not results:
        return {
            "match_score": 0,
            "recommendation": "EVALUATION_FAILED",
            "requirements": [],
            "strengths": [],
            "gaps": [],
            "summary": (
                "No fue posible evaluar al candidato porque "
                "no se encontró información relevante en el Knowledge Base."
            ),
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

    # Normalize requirement names
    def normalize_requirement(requirement: str) -> str:
        requirement = str(requirement).strip()
        lower = requirement.lower()
        if "python" in lower:
            return "Python"
        if any(x in lower for x in ("api rest", "apis rest", "rest api", "rest apis")):
            return "APIs REST"
        if "aws" in lower:
            return "AWS"
        if "kubernetes" in lower:
            return "Kubernetes"
        if any(
            x in lower
            for x in (
                "backend developer",
                "backend development",
                "desarrollo backend",
                "desarrollador backend",
            )
        ) or lower == "backend":
            return "Backend Developer"
        return requirement

    # STEP 1: Extract requirements from job description
    extraction_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
Eres un extractor estricto de requisitos de vacantes.

Tu única tarea es identificar los requisitos explícitos
mencionados en la descripción de la vacante.

REGLAS:

1. Usa exclusivamente la descripción proporcionada.
2. No uses conocimiento externo.
3. No inventes requisitos.
4. No agregues tecnologías que no aparezcan.
5. No agregues requisitos implícitos.
6. No agregues requisitos derivados.
7. Cada requisito debe estar explícitamente mencionado.
8. Elimina duplicados.
9. Mantén requisitos técnicos y profesionales relevantes.
10. No evalúes al candidato.

Devuelve exclusivamente JSON válido.

FORMATO:

{{
    "requirements": [
        "Desarrollo backend",
        "Python",
        "APIs REST",
        "AWS",
        "Kubernetes"
    ]
}}

No escribas explicaciones.
No escribas Markdown.
No utilices bloques de código.

DESCRIPCIÓN DE LA VACANTE:

{job_description}

{_retry_instruction}
""",
            ),
            ("human", "Extrae únicamente los requisitos explícitos."),
        ]
    )

    extraction_chain = extraction_prompt | llm
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
            "summary": (
                "No se pudieron identificar requisitos "
                "explícitos en la descripción de la vacante."
            ),
        }

    # STEP 2: Prepare requirements text
    requirements_text = "\n".join(f"- {r}" for r in requirements_from_job)

    # STEP 3: Evaluate requirements against CV
    evaluation_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
    Eres un sistema experto en evaluación de candidatos.

    Debes comparar el CV del candidato contra los requisitos
    del cargo.

    Analiza únicamente la información presente en el CV.

    Para cada requisito debes determinar:

    MATCH:
    Existe evidencia clara de que el candidato cumple
    el requisito.

    PARTIAL:
    Existe evidencia relacionada o parcial, pero no suficiente
    para afirmar que lo cumple completamente.

    MISSING:
    No existe evidencia suficiente en el CV.

    IMPORTANTE:

    - No inventes información.
    - No asumas experiencia.
    - No uses conocimiento externo.
    - Si un requisito no aparece explícitamente en el CV,
    utiliza MISSING.
    - Si utilizas PARTIAL, explica claramente por qué.
    - La evidencia debe salir exclusivamente del CV.
    - Evalúa TODOS los requisitos proporcionados.
    - No agregues requisitos nuevos.

    Devuelve exclusivamente JSON válido.

    No escribas Markdown.
    No escribas ```json.
    No agregues explicaciones fuera del JSON.

    ESTRUCTURA EXACTA:

    {{
        "requirements": [
            {{
                "requirement": "nombre del requisito",
                "status": "MATCH",
                "evidence": "evidencia encontrada en el CV"
            }}
        ]
    }}

    Los únicos valores permitidos para status son:

    MATCH
    PARTIAL
    MISSING

    Cuando el status sea MISSING:

    "evidence": null

    Cuando el status sea MATCH o PARTIAL:

    "evidence" debe contener evidencia concreta
    encontrada en el CV.

    {_retry_instruction}
    """,
            ),
            (
                "human",
                """
    REQUISITOS DEL CARGO:

    {requirements}

    CV DEL CANDIDATO:

    {context}
    """,
            ),
        ]
    )

    evaluation_chain = evaluation_prompt | llm
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
    if match_score >= 80:
        recommendation = "STRONG_MATCH"
    elif match_score >= 60:
        recommendation = "PARTIAL_MATCH"
    else:
        recommendation = "LOW_MATCH"

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

    summary = (
        f"El candidato cumple completamente "
        f"{match_count} de {total} requisitos, "
        f"cumple parcialmente {partial_count} "
        f"y no presenta evidencia explícita para "
        f"{missing_count}."
    )

    return {
        "match_score": match_score,
        "recommendation": recommendation,
        "requirements": final_requirements,
        "strengths": strengths,
        "gaps": gaps,
        "summary": summary,
    }
