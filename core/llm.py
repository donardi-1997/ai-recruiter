import json

from langchain_aws import ChatBedrock
from langchain_core.prompts import ChatPromptTemplate

from core.config import AWS_REGION, KNOWLEDGE_BASE_ID, NUMBER_OF_RESULTS
from core.aws_clients import bedrock_agent_runtime
from core.helpers import invoke_json_prompt

# ============================================================
# LLM
# ============================================================

llm = ChatBedrock(
    model_id="amazon.nova-lite-v1:0",
    region_name=AWS_REGION,
    model_kwargs={"temperature": 0},
)


# ============================================================
# RETRIEVE CANDIDATE FROM BEDROCK KNOWLEDGE BASE
# ============================================================


def retrieve_candidate(candidate_id: str, question: str) -> list:
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
    print(f">>> RETRIEVE candidate_id={candidate_id}")
    print(f">>> RESULTADOS ENCONTRADOS={len(results)}")
    for result in results:
        metadata = result.get("metadata", {})
        print(
            ">>> RESULT:",
            result.get("location", {}),
            "candidate_id=",
            metadata.get("candidate_id"),
            "score=",
            result.get("score"),
        )
    return results


# ============================================================
# GENERATE ANSWER
# ============================================================


def generate_answer(candidate_id: str, question: str, results: list):
    context_parts = []
    for result in results:
        text = result.get("content", {}).get("text", "")
        if text:
            context_parts.append(text)
    context = "\n\n---\n\n".join(context_parts)

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
Eres un especialista en selección de talento técnico.

Tu tarea es responder preguntas sobre el candidato utilizando
EXCLUSIVAMENTE la información encontrada en el CV proporcionado.

REGLAS:

- No inventes información.
- No asumas experiencia que no aparece en el CV.
- Si la información no aparece en el contexto, dilo claramente.
- Responde en español.
- Sé preciso y conciso.
- Puedes utilizar listas cuando ayuden a la claridad.
- No necesitas devolver JSON.
""",
            ),
            (
                "human",
                """
CANDIDATE ID:
{candidate_id}

PREGUNTA:
{question}

CV CONTEXT:
{context}
""",
            ),
        ]
    )

    chain = prompt | llm
    response = chain.invoke(
        {
            "candidate_id": candidate_id,
            "question": question,
            "context": context,
        }
    )
    return str(response.content)


# ============================================================
# EVALUATE CANDIDATE
# ============================================================


def evaluate_candidate(
    candidate_id: str, job_description: str, results: list
):
    if not results:
        return {
            "match_score": 0,
            "recommendation": "LOW_MATCH",
            "requirements": [],
            "strengths": [],
            "gaps": ["No se encontró información relevante en el CV."],
            "summary": (
                "No fue posible evaluar al candidato porque "
                "no se encontró información relevante en su CV."
            ),
        }

    context_parts = []
    for result in results:
        text = result.get("content", {}).get("text", "")
        if text:
            context_parts.append(text)
    context = "\n\n---\n\n".join(context_parts)

    def normalize_requirement(requirement: str) -> str:
        requirement = str(requirement).strip()
        lower = requirement.lower()
        if "python" in lower:
            return "Python"
        if any(
            x in lower
            for x in ("api rest", "apis rest", "rest api", "rest apis")
        ):
            return "APIs REST"
        if "aws" in lower:
            return "AWS"
        if "kubernetes" in lower:
            return "Kubernetes"
        if (
            "backend developer" in lower
            or "backend development" in lower
            or "desarrollo backend" in lower
            or "desarrollador backend" in lower
            or lower == "backend"
        ):
            return "Backend Developer"
        return requirement

    # STEP 1: Extract requirements
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

    requirements_text = "\n".join(f"- {r}" for r in requirements_from_job)

    # STEP 2: Evaluate requirements
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
        {
            "requirements": requirements_text,
            "context": context,
            "_retry_instruction": "",
        },
        "evaluar requisitos contra CV",
    )

    # Normalize results
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

    # Guarantee all requirements present
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

    if match_score >= 80:
        recommendation = "STRONG_MATCH"
    elif match_score >= 60:
        recommendation = "PARTIAL_MATCH"
    else:
        recommendation = "LOW_MATCH"

    strengths = [
        r.get("requirement")
        for r in final_requirements
        if r.get("status") == "MATCH"
    ]

    gaps = [
        r.get("requirement")
        for r in final_requirements
        if r.get("status") in {"PARTIAL", "MISSING"}
    ]

    match_count = sum(
        1 for r in final_requirements if r["status"] == "MATCH"
    )
    partial_count = sum(
        1 for r in final_requirements if r["status"] == "PARTIAL"
    )
    missing_count = sum(
        1 for r in final_requirements if r["status"] == "MISSING"
    )

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


# ============================================================
# EVALUATE AND SAVE (shared service)
# ============================================================


def evaluate_and_save(
    candidate_id: str,
    job_id: str,
    current_user: dict,
) -> dict:
    """Evaluate a candidate against a job and save the evaluation to DynamoDB.

    Returns the full evaluation dict (match_score, recommendation, etc.)
    Raises ValueError if candidate/job not found or access denied.
    """
    import json
    from datetime import datetime, timezone

    from core.helpers import (
        get_candidate_record,
        get_job_record,
        save_evaluation_record,
        build_sources,
    )

    candidate = get_candidate_record(candidate_id)
    if not candidate:
        raise ValueError("Candidato no encontrado.")

    job = get_job_record(job_id)
    if not job:
        raise ValueError("Vacante no encontrada.")

    if candidate.get("owner_id") != current_user["sub"]:
        raise ValueError("No tienes permiso sobre este candidato.")

    if job.get("owner_id") != current_user["sub"]:
        raise ValueError("No tienes permiso para acceder a esta vacante.")

    results = retrieve_candidate(
        candidate_id=candidate_id, question=job["description"]
    )
    evaluation = evaluate_candidate(
        candidate_id=candidate_id,
        job_description=job["description"],
        results=results,
    )

    evaluation_record = {
        "job_id": job_id,
        "job_title": job.get("title", ""),
        "job_description": job.get("description", ""),
        "candidate_id": candidate_id,
        "candidate_name": candidate.get("name", ""),
        "owner_id": job["owner_id"],
        "status": "COMPLETED",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "match_score": int(evaluation.get("match_score", 0)),
        "recommendation": evaluation.get("recommendation", "LOW_MATCH"),
        "requirements": json.dumps(
            evaluation.get("requirements", []), ensure_ascii=False
        ),
        "strengths": json.dumps(
            evaluation.get("strengths", []), ensure_ascii=False
        ),
        "gaps": json.dumps(evaluation.get("gaps", []), ensure_ascii=False),
        "summary": evaluation.get("summary", ""),
    }
    save_evaluation_record(evaluation_record)

    sources = build_sources(results)
    return {
        "candidate_id": candidate_id,
        "match_score": evaluation.get("match_score", 0),
        "recommendation": evaluation.get("recommendation", "LOW_MATCH"),
        "requirements": evaluation.get("requirements", []),
        "strengths": evaluation.get("strengths", []),
        "gaps": evaluation.get("gaps", []),
        "summary": evaluation.get("summary", ""),
        "sources": sources,
    }
