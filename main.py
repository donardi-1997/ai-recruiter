import json
import os
import re
import uuid
from io import BytesIO
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key, Attr
import requests

from auth import (
    create_user,
    login_user
)

from dotenv import load_dotenv

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    Depends
)

from fastapi.security import (
    HTTPBearer,
    HTTPAuthorizationCredentials
)

from fastapi.middleware.cors import CORSMiddleware

from jose import jwt

from pydantic import BaseModel, Field
from PyPDF2 import PdfReader

from langchain_aws import ChatBedrock
from langchain_core.prompts import ChatPromptTemplate

from auth import LoginRequest, login_user

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()


# ============================================================
# AWS CONFIGURATION
# ============================================================

AWS_REGION = os.getenv(
    "AWS_REGION",
    "us-east-2"
)

KNOWLEDGE_BASE_ID = "CP7BI7MQVB"

DATA_SOURCE_ID = "9A6HM1WZQR"

S3_BUCKET = "ai-cv-rag-adrian-2026"

S3_PREFIX = "documents"

NUMBER_OF_RESULTS = 50
MAX_CV_SIZE_BYTES = 15 * 1024 * 1024


# ============================================================
# COGNITO CONFIGURATION
# ============================================================

COGNITO_USER_POOL_ID = os.getenv(
    "COGNITO_USER_POOL_ID"
)

COGNITO_CLIENT_ID = os.getenv(
    "COGNITO_CLIENT_ID"
)

COGNITO_ISSUER = (
    f"https://cognito-idp.{AWS_REGION}.amazonaws.com/"
    f"{COGNITO_USER_POOL_ID}"
)

COGNITO_JWKS_URL = (
    f"{COGNITO_ISSUER}/.well-known/jwks.json"
)


print(
    "COGNITO USER POOL:",
    COGNITO_USER_POOL_ID
)

print(
    "COGNITO CLIENT ID:",
    COGNITO_CLIENT_ID
)

print(
    "COGNITO ISSUER:",
    COGNITO_ISSUER
)


# ============================================================
# COGNITO AUTHENTICATION
# ============================================================

security = HTTPBearer()

_cognito_jwks = None

# ============================================================
# GET COGNITO JWKS
# ============================================================

def get_cognito_jwks():

    global _cognito_jwks

    if _cognito_jwks is None:

        response = requests.get(
            COGNITO_JWKS_URL,
            timeout=10
        )

        response.raise_for_status()

        _cognito_jwks = response.json()

    return _cognito_jwks


# ============================================================
# VALIDATE COGNITO JWT
# ============================================================

# ============================================================
# VALIDATE COGNITO ACCESS TOKEN
# ============================================================

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(
        security
    )
):

    token = credentials.credentials

    try:

        # ====================================================
        # JWT HEADER
        # ====================================================

        header = jwt.get_unverified_header(
            token
        )

        kid = header.get(
            "kid"
        )

        if not kid:

            raise HTTPException(
                status_code=401,
                detail="JWT sin kid."
            )

        # ====================================================
        # COGNITO PUBLIC KEYS
        # ====================================================

        jwks = get_cognito_jwks()

        key = next(
            (
                key
                for key in jwks["keys"]
                if key["kid"] == kid
            ),
            None
        )

        if not key:

            raise HTTPException(
                status_code=401,
                detail="Clave JWT no encontrada."
            )

        # ====================================================
        # DECODE + SIGNATURE + ISSUER + EXPIRATION
        # ====================================================

        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=COGNITO_ISSUER,
            options={
                "verify_aud": False
            }
        )

        # ====================================================
        # VALIDATE TOKEN TYPE
        # ====================================================

        token_use = payload.get(
            "token_use"
        )

        if token_use != "access":

            raise HTTPException(
                status_code=401,
                detail="Se requiere un Cognito Access Token."
            )

        # ====================================================
        # VALIDATE CLIENT ID
        # ====================================================

        token_client_id = payload.get(
            "client_id"
        )

        if token_client_id != COGNITO_CLIENT_ID:

            raise HTTPException(
                status_code=401,
                detail="El token no pertenece a esta aplicación."
            )

        # ====================================================
        # VALIDATE SUBJECT
        # ====================================================

        if not payload.get("sub"):

            raise HTTPException(
                status_code=401,
                detail="JWT sin identificador de usuario."
            )

        print(
            "JWT VALIDATED:",
            {
                "sub": payload.get("sub"),
                "username": payload.get("username"),
                "token_use": payload.get("token_use"),
                "client_id": payload.get("client_id")
            }
        )

        return payload

    except HTTPException:

        raise

    except Exception as e:

        print(
            "JWT VALIDATION ERROR:",
            str(e)
        )

        raise HTTPException(
            status_code=401,
            detail="Token inválido o expirado."
        )

# ============================================================
# CURRENT USER ID
# ============================================================

def get_current_owner_id(
    current_user: dict = Depends(get_current_user)
):

    return current_user["sub"]

# ============================================================
# CONFIGURACIÓN
# ============================================================

AWS_REGION = "us-east-2"
KNOWLEDGE_BASE_ID = "CP7BI7MQVB"
DATA_SOURCE_ID = "9A6HM1WZQR"
S3_BUCKET = "ai-cv-rag-adrian-2026"
S3_PREFIX = "documents"
NUMBER_OF_RESULTS = 50

# ============================================================
# DYNAMODB
# ============================================================

CANDIDATES_TABLE = "ai-recruiter-candidates"
JOBS_TABLE = "ai-recruiter-jobs"
EVALUATIONS_TABLE = "ai-recruiter-evaluations"

# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="AI Recruiter API",
    description=(
        "API de gestión y consulta de candidatos "
        "usando Amazon Bedrock Knowledge Bases"
    ),
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # Desarrollo local
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",

        # Producción
        "https://ai.adrianguerra.net",
        "https://d2c1mv108wl5wv.cloudfront.net",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LoginRequest(BaseModel):
    email: str
    password: str

# ============================================================
# AUTH - REGISTER USER (COGNITO)
# ============================================================

@app.post("/api/auth/register"
)
def register_user(
    email: str,
    password: str
):

    return create_user(
        email,
        password
    )


# ============================================================
# AUTH - LOGIN USER (COGNITO)
# ============================================================

@app.post("/api/auth/login")
def login(
    data: LoginRequest
):

    result = login_user(
        data.email,
        data.password
    )

    if result.get("error"):

        raise HTTPException(
            status_code=401,
            detail=result["error"]
        )

    return result

# ============================================================
# AUTH - CURRENT USER
# ============================================================

@app.get("/api/auth/me"
)
def get_current_user_info(
    current_user: dict = Depends(
        get_current_user
    )
):

    return {
        "authenticated": True,
        "user": current_user
    }

# ============================================================
# AWS CLIENTS
# ============================================================

s3 = boto3.client(
    "s3",
    region_name=AWS_REGION
)
bedrock_agent = boto3.client(
    "bedrock-agent",
    region_name=AWS_REGION
)
bedrock_agent_runtime = boto3.client(
    "bedrock-agent-runtime",
    region_name=AWS_REGION
)
dynamodb = boto3.resource(
    "dynamodb",
    region_name=AWS_REGION
)
candidates_table = dynamodb.Table(
    CANDIDATES_TABLE
)
jobs_table = dynamodb.Table(
    JOBS_TABLE
)
evaluations_table = dynamodb.Table(
    EVALUATIONS_TABLE
)

# ============================================================
# LLM
# ============================================================
llm = ChatBedrock(
    model_id="amazon.nova-lite-v1:0",
    region_name=AWS_REGION,
    model_kwargs={
        "temperature": 0
    }
)

# ============================================================
# REQUEST / RESPONSE MODELS
# ============================================================


class AskCandidateRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        description="Pregunta sobre el candidato"
    )

class Source(BaseModel):
    file: str | None = None
    score: float
    page: int | None = None

class AskCandidateResponse(BaseModel):
    candidate_id: str
    answer: str
    sources: list[Source]

class EvaluateCandidateRequest(BaseModel):
    job_description: str = Field(
        ...,
        min_length=10,
        description="Descripción de la vacante"
    )

class CreateJobRequest(BaseModel):
    title: str = Field(
        ...,
        min_length=3,
        description="Título de la vacante"
    )
    description: str = Field(
        ...,
        min_length=10,
        description="Descripción completa de la vacante"
    )

class EvaluateJobRequest(BaseModel):
    job_id: str

class JobResponse(BaseModel):
    job_id: str
    title: str
    description: str

class RequirementEvaluation(BaseModel):
    requirement: str
    status: str
    evidence: str | None = None

class CandidateEvaluation(BaseModel):
    candidate_id: str
    match_score: int
    recommendation: str
    requirements: list[RequirementEvaluation] = Field(
        default_factory=list
    )
    strengths: list[str] = Field(
        default_factory=list
    )
    gaps: list[str] = Field(
        default_factory=list
    )
    summary: str
    sources: list[Source] = Field(
        default_factory=list
    )

class CandidateRankingItem(BaseModel):
    rank: int
    candidate_id: str
    candidate_name: str

    match_score: int | None = None

    recommendation: str

    status: str

    strengths: list[str] = Field(
        default_factory=list
    )

    gaps: list[str] = Field(
        default_factory=list
    )

class JobRankingResponse(BaseModel):
    job_id: str
    job_title: str
    page: int
    page_size: int
    total: int
    total_pages: int
    candidates: list[
        CandidateRankingItem
    ]

class CandidateJobEvaluationResponse(BaseModel):
    job_id: str
    candidate_id: str
    candidate_name: str
    candidate_filename: str
    match_score: int
    recommendation: str
    requirements: list
    strengths: list[str]
    gaps: list[str]
    summary: str

class JobSummaryTopCandidate(BaseModel):
    candidate_id: str
    candidate_name: str
    match_score: int
    recommendation: str

class JobSummaryResponse(BaseModel):
    job_id: str
    job_title: str
    total_candidates: int
    evaluated_candidates: int
    pending_candidates: int
    failed_candidates: int
    strong_matches: int
    partial_matches: int
    low_matches: int
    average_score: float
    top_candidate: JobSummaryTopCandidate | None

class CandidateComparisonItem(BaseModel):
    candidate_id: str
    candidate_name: str
    match_score: int
    recommendation: str
    strengths: list[str]
    gaps: list[str]


class CandidateComparisonResponse(BaseModel):
    job_id: str
    job_title: str
    candidates: list[CandidateComparisonItem]
    winner: CandidateComparisonItem | None

class CandidateRequirementItem(BaseModel):
    requirement: str
    status: str
    evidence: str | None = None

class CandidateRequirementsResponse(BaseModel):
    job_id: str
    job_title: str
    candidate_id: str
    candidate_name: str
    match_score: int
    recommendation: str
    requirements: list[CandidateRequirementItem]


# ============================================================
# JSON CLEANER
# ============================================================
def clean_json(content: str) -> str:
    if not content:
        raise ValueError(
            "El modelo devolvió una respuesta vacía."
        )
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
            "No se encontró un objeto JSON en la respuesta: "
            f"{content}"
        )
    end = content.rfind("}")
    if end == -1 or end < start:
        raise ValueError(
            "El JSON está incompleto: "
            f"{content}"
        )
    return content[start:end + 1].strip()

# ============================================================
# INVOKE JSON PROMPT
# ============================================================
def invoke_json_prompt(
    chain,
    payload: dict,
    description: str
):
    response = chain.invoke(
        payload
    )
    raw_content = response.content
    cleaned_content = clean_json(
        raw_content
    )
    try:
        return json.loads(
            cleaned_content
        )
    except json.JSONDecodeError as first_error:
        print(
            f"JSON inválido en {description}."
        )
        print(
            f"Primer error: {first_error}"
        )
        print(
            f"Respuesta recibida: {raw_content}"
        )
    retry_payload = dict(
        payload
    )
    retry_payload[
        "_retry_instruction"
    ] = """
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
    retry_response = chain.invoke(
        retry_payload
    )
    retry_raw_content = (
        retry_response.content
    )
    retry_cleaned_content = clean_json(
        retry_raw_content
    )
    try:
        return json.loads(
            retry_cleaned_content
        )
    except json.JSONDecodeError as second_error:
        raise ValueError(
            f"El modelo no devolvió JSON válido "
            f"al {description}. "
            f"Primer error: {first_error}. "
            f"Segundo error: {second_error}. "
            f"Respuesta: {retry_cleaned_content}"
        ) from second_error

# ============================================================
# HELPERS DYNAMODB
# ============================================================
def get_candidate_record(
    candidate_id: str
):
    response = candidates_table.get_item(
        Key={
            "candidate_id": candidate_id
        }
    )
    return response.get(
        "Item"
    )

def get_job_record(
    job_id: str
):
    response = jobs_table.get_item(
        Key={
            "job_id": job_id
        }
    )
    return response.get(
        "Item"
    )

def validate_job_owner(
    job: dict,
    current_user: dict
):
    if job.get("owner_id") != current_user["sub"]:
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para acceder a esta vacante."
        )

def save_candidate_record(
    candidate: dict
):
    candidates_table.put_item(
        Item=candidate
    )

def save_job_record(
    job: dict
):
    jobs_table.put_item(
        Item=job
    )

def save_evaluation_record(
    evaluation: dict
):
    evaluations_table.put_item(
        Item=evaluation
    )

def parse_json_field(value):

    if isinstance(value, str):

        try:
            return json.loads(value)

        except:
            return value

    return value
# ============================================================
# BUILD SOURCES
# ============================================================
def build_sources(
    results: list
) -> list[Source]:
    sources_dict = {}
    for result in results:
        location = result.get(
            "location",
            {}
        )
        s3_location = location.get(
            "s3Location",
            {}
        )
        uri = s3_location.get(
            "uri"
        )
        metadata = result.get(
            "metadata",
            {}
        )
        page = metadata.get(
            "x-amz-bedrock-kb-document-page-number"
        )
        score = result.get(
            "score",
            0
        )
        try:
            score = float(
                score or 0
            )
        except Exception:
            score = 0
        try:
            page_value = (
                int(page)
                if page is not None
                else None
            )
        except Exception:
            page_value = None
        key = (
            uri,
            page_value
        )
        if (
            key not in sources_dict
            or score > sources_dict[key].score
        ):
            sources_dict[key] = Source(
                file=uri,
                score=score,
                page=page_value
            )
    return list(
        sources_dict.values()
    )

# ============================================================
# RETRIEVE CANDIDATE
# ============================================================
def retrieve_candidate(
    candidate_id: str,
    question: str
):
    response = bedrock_agent_runtime.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={
            "text": question
        },
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": NUMBER_OF_RESULTS,
                "filter": {
                    "equals": {
                        "key": "candidate_id",
                        "value": candidate_id
                    }
                }
            }
        }
    )
    results = response.get(
        "retrievalResults",
        []
    )
    print(
        f">>> RETRIEVE candidate_id={candidate_id}"
    )
    print(
        f">>> RESULTADOS ENCONTRADOS={len(results)}"
    )
    for result in results:
        metadata = result.get(
            "metadata",
            {}
        )
        print(
            ">>> RESULT:",
            result.get("location", {}),
            "candidate_id=",
            metadata.get("candidate_id"),
            "score=",
            result.get("score")
        )
    return results

# ============================================================
# GENERATE ANSWER
# ============================================================
def generate_answer(
    candidate_id: str,
    question: str,
    results: list
):
    context_parts = []

    for result in results:
        text = (
            result
            .get("content", {})
            .get("text", "")
        )

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
"""
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
"""
            ),
        ]
    )

    chain = prompt | llm

    response = chain.invoke(
        {
            "candidate_id": candidate_id,
            "question": question,
            "context": context
        }
    )

    return str(response.content)

# ============================================================
# EVALUATE CANDIDATE
# ============================================================
def evaluate_candidate(
    candidate_id: str,
    job_description: str,
    results: list
):
    # ========================================================
    # SIN RESULTADOS
    # ========================================================
    if not results:
        return {
            "match_score": 0,
            "recommendation": "LOW_MATCH",
            "requirements": [],
            "strengths": [],
            "gaps": [
                "No se encontró información relevante en el CV."
            ],
            "summary": (
                "No fue posible evaluar al candidato porque "
                "no se encontró información relevante en su CV."
            )
        }

    # ========================================================
    # CONSTRUIR CONTEXTO DEL CV
    # ========================================================
    context_parts = []

    for result in results:
        text = (
            result
            .get("content", {})
            .get("text", "")
        )

        if text:
            context_parts.append(text)

    context = "\n\n---\n\n".join(context_parts)

    print("=" * 60)
    print("CONTEXTO DEL CANDIDATO")
    print("=" * 60)
    print(context)
    print("=" * 60)

    # ========================================================
    # NORMALIZAR REQUISITO
    # ========================================================
    def normalize_requirement(
        requirement: str
    ) -> str:

        requirement = str(
            requirement
        ).strip()

        lower = requirement.lower()

        if "python" in lower:
            return "Python"

        if (
            "api rest" in lower
            or "apis rest" in lower
            or "rest api" in lower
            or "rest apis" in lower
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

    # ========================================================
    # PASO 1 - EXTRAER REQUISITOS
    # ========================================================
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
"""
            ),
            (
                "human",
                "Extrae únicamente los requisitos explícitos."
            )
        ]
    )

    extraction_chain = (
        extraction_prompt | llm
    )

    extraction = invoke_json_prompt(
        extraction_chain,
        {
            "job_description": job_description,
            "_retry_instruction": ""
        },
        "extraer requisitos"
    )

    print(
        ">>> RESPUESTA EXTRACCIÓN:",
        extraction
    )

    # ========================================================
    # OBTENER REQUISITOS
    # ========================================================
    requirements_from_job = extraction.get(
        "requirements",
        []
    )

    if not isinstance(
        requirements_from_job,
        list
    ):
        requirements_from_job = []

    # ========================================================
    # NORMALIZAR REQUISITOS
    # ========================================================
    normalized_requirements = []

    seen = set()

    for requirement in requirements_from_job:

        if not isinstance(
            requirement,
            str
        ):
            continue

        normalized = normalize_requirement(
            requirement
        ).strip()

        if not normalized:
            continue

        key = normalized.lower()

        if key not in seen:
            seen.add(key)

            normalized_requirements.append(
                normalized
            )

    requirements_from_job = (
        normalized_requirements
    )

    print(
        ">>> REQUISITOS NORMALIZADOS:",
        requirements_from_job
    )

    # ========================================================
    # SI NO HAY REQUISITOS
    # ========================================================
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
            )
        }
    # ========================================================
    # PASO 2 - PREPARAR REQUISITOS
    # ========================================================
    requirements_text = "\n".join(
        f"- {requirement}"
        for requirement
        in requirements_from_job
    )

    print(
        ">>> REQUISITOS PARA EVALUAR:"
    )
    print(requirements_text)


    # ========================================================
    # PASO 3 - EVALUAR REQUISITOS
    # ========================================================
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
    """
            ),
            (
                "human",
                """
    REQUISITOS DEL CARGO:

    {requirements}

    CV DEL CANDIDATO:

    {context}
    """
            )
        ]
    )

    evaluation_chain = (
        evaluation_prompt | llm
    )


    # ========================================================
    # INVOCAR EVALUACIÓN
    # ========================================================
    evaluation = invoke_json_prompt(
        evaluation_chain,
        {
            "requirements": requirements_text,
            "context": context,
            "_retry_instruction": ""
        },
        "evaluar requisitos contra CV"
    )

    print("=" * 80)
    print(">>> EVALUACIÓN RAW DEL LLM")
    print(evaluation)
    print("=" * 80)

    print(
        ">>> RESPUESTA EVALUACIÓN:",
        evaluation
    )

    # ========================================================
    # NORMALIZAR RESULTADOS
    # ========================================================

    raw_requirements = evaluation.get(
        "requirements",
        []
    )

    valid_statuses = {
        "MATCH",
        "PARTIAL",
        "MISSING"
    }

    evaluated = {}

    for item in raw_requirements:

        if not isinstance(
            item,
            dict
        ):
            continue

        requirement = str(
            item.get(
                "requirement",
                ""
            )
        ).strip()

        if not requirement:
            continue

        # Normalizar exactamente igual que los requisitos
        normalized_requirement = normalize_requirement(
            requirement
        ).strip()

        status = str(
            item.get(
                "status",
                "MISSING"
            )
        ).upper().strip()

        if status not in valid_statuses:
            status = "MISSING"

        evidence = item.get(
            "evidence"
        )

        # MISSING siempre tiene evidence null
        if status == "MISSING":
            evidence = None

        elif evidence is not None:

            evidence = str(
                evidence
            ).strip()

            words = evidence.split()

            if len(words) > 30:
                evidence = (
                    " ".join(words[:30])
                    + "..."
                )

        key = normalized_requirement.lower().strip()

        evaluated[key] = {
            "requirement": normalized_requirement,
            "status": status,
            "evidence": evidence
        }

    print("=" * 80)
    print(">>> EVALUATED NORMALIZADO")
    print(evaluated)
    print("=" * 80)

    # ========================================================
    # GARANTIZAR TODOS LOS REQUISITOS
    # ========================================================

    final_requirements = []

    for requirement in requirements_from_job:

        normalized_requirement = normalize_requirement(
            requirement
        ).strip()

        key = normalized_requirement.lower().strip()

        existing = evaluated.get(
            key
        )

        print(
            ">>> REQUISITO FINAL:",
            normalized_requirement,
            "=>",
            existing
        )

        if existing:

            final_requirements.append(
                {
                    "requirement": normalized_requirement,
                    "status": existing.get(
                        "status",
                        "MISSING"
                    ),
                    "evidence": existing.get(
                        "evidence"
                    )
                }
            )

        else:

            final_requirements.append(
                {
                    "requirement": normalized_requirement,
                    "status": "MISSING",
                    "evidence": None
                }
            )


    # ========================================================
    # SCORE
    # ========================================================

    total = len(
        final_requirements
    )

    points = 0

    for requirement in final_requirements:

        status = requirement.get(
            "status",
            "MISSING"
        )

        if status == "MATCH":

            points += 1

        elif status == "PARTIAL":

            points += 0.5


    if total > 0:

        match_score = round(
            (points / total) * 100
        )

    else:

        match_score = 0


    # ========================================================
    # RECOMMENDATION
    # ========================================================

    if match_score >= 80:

        recommendation = "STRONG_MATCH"

    elif match_score >= 60:

        recommendation = "PARTIAL_MATCH"

    else:

        recommendation = "LOW_MATCH"


    # ========================================================
    # STRENGTHS
    # ========================================================

    strengths = []

    for requirement in final_requirements:

        if requirement.get(
            "status"
        ) == "MATCH":

            strengths.append(
                requirement.get(
                    "requirement"
                )
            )


    # ========================================================
    # GAPS
    # ========================================================

    gaps = []

    for requirement in final_requirements:

        if requirement.get(
            "status"
        ) in {
            "PARTIAL",
            "MISSING"
        }:

            gaps.append(
                requirement.get(
                    "requirement"
                )
            )
            
    # ========================================================
    # SUMMARY
    # ========================================================
    match_count = sum(
        1
        for requirement
        in final_requirements
        if requirement["status"] == "MATCH"
    )

    partial_count = sum(
        1
        for requirement
        in final_requirements
        if requirement["status"] == "PARTIAL"
    )

    missing_count = sum(
        1
        for requirement
        in final_requirements
        if requirement["status"] == "MISSING"
    )

    summary = (
        f"El candidato cumple completamente "
        f"{match_count} de {total} requisitos, "
        f"cumple parcialmente {partial_count} "
        f"y no presenta evidencia explícita para "
        f"{missing_count}."
    )

    print("=" * 80)
    print(">>> FINAL REQUIREMENTS")
    print(final_requirements)
    print(">>> MATCH SCORE")
    print(match_score)
    print(">>> RECOMMENDATION")
    print(recommendation)
    print("=" * 80)

    return {
        "match_score": match_score,
        "recommendation": recommendation,
        "requirements": final_requirements,
        "strengths": strengths,
        "gaps": gaps,
        "summary": summary
    }

    # ========================================================
    # RESULTADO FINAL
    # ========================================================
    return {
        "match_score": match_score,
        "recommendation": recommendation,
        "requirements": final_requirements,
        "strengths": strengths,
        "gaps": gaps,
        "summary": summary
    }

# ============================================================
# ENDPOINTS
# ============================================================

# ============================================================
# HEALTH
# ============================================================
@app.get("/api/")
def root():
    return {
        "service": "AI Recruiter API",
        "status": "ok"
    }

@app.get("/api/health")
def health():
    return {
        "status": "healthy"
    }

# ============================================================
# CREATE JOB
# ============================================================
@app.post("/api/jobs",
    response_model=JobResponse
)
def create_job(
    request: CreateJobRequest,
    current_user: dict = Depends(get_current_user)
):
    try:
        job_id = str(
            uuid.uuid4()
        )
        job = {
            "job_id": job_id,
            "title": request.title.strip(),
            "description": request.description.strip(),
            "owner_id": current_user["sub"]
        }
        save_job_record(
            job
        )
        print(
            "JOB CREATED:",
            job_id
        )
        return JobResponse(
            **job
        )
    except Exception as e:
        print(
            f"ERROR CREATE JOB: {str(e)}"
        )
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# LIST JOBS
# ============================================================
@app.get("/api/jobs"
)
def list_jobs(
    current_user: dict = Depends(get_current_user)
):
    try:
        response = jobs_table.scan()

        jobs = response.get(
            "Items",
            []
        )

        owner_id = current_user["sub"]

        user_jobs = [
            job
            for job in jobs
            if job.get("owner_id") == owner_id
        ]

        return {
            "jobs": user_jobs
        }
    except Exception as e:
        print(
            f"ERROR LIST JOBS: {str(e)}"
        )
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# CREATE CANDIDATE / UPLOAD CV
# ============================================================
def _clean_extracted_text(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n-|•")
    return value or None


def extract_candidate_profile_from_pdf(pdf_bytes: bytes) -> dict:
    reader = PdfReader(BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    lines = [_clean_extracted_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    email = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.I)
    phone = re.search(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)", text)
    name = None
    for line in lines[:12]:
        words = line.split()
        if 2 <= len(words) <= 5 and (not email or email.group(0).lower() not in line.lower()):
            if all(re.match(r"^[^\W\d_][\w'’-]*$", word, re.UNICODE) for word in words):
                name = line
                break
    location = None
    title = None
    for line in lines[:40]:
        lower = line.lower()
        if ":" in line and any(x in lower for x in ("ubicación", "location", "ciudad", "dirección")):
            location = _clean_extracted_text(line.split(":", 1)[1])
        if ":" in line and any(x in lower for x in ("perfil", "professional title", "cargo", "title")):
            title = _clean_extracted_text(line.split(":", 1)[1])
    if not title:
        title = next((line for line in lines[:20] if any(
            x in line.lower() for x in ("developer", "engineer", "manager", "designer", "analyst",
                                        "desarrollador", "ingeniero", "gerente")
        )), None)
    return {
        "name": _clean_extracted_text(name),
        "email": _clean_extracted_text(email.group(0) if email else None),
        "phone": _clean_extracted_text(phone.group(0) if phone else None),
        "location": location,
        "professional_title": _clean_extracted_text(title),
    }


def _fallback_candidate_name(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename))[0]
    return _clean_extracted_text(re.sub(r"[_-]+", " ", stem)) or "Candidato"


def _service_error_message(error: Exception) -> str:
    response = getattr(error, "response", {})
    aws_error = response.get("Error", {}) if isinstance(response, dict) else {}
    return aws_error.get("Message", "No fue posible completar el registro del candidato.")


async def _prepare_bulk_candidate(file: UploadFile, current_user: dict) -> dict:
    original_filename = os.path.basename(file.filename or "")
    if not original_filename.lower().endswith(".pdf"):
        raise ValueError("El CV debe estar en formato PDF.")
    content = await file.read()
    if not content:
        raise ValueError("El archivo está vacío.")
    if len(content) > MAX_CV_SIZE_BYTES:
        raise ValueError("El archivo supera el límite de 15 MB.")
    if not content.startswith(b"%PDF"):
        raise ValueError("El archivo no tiene una firma PDF válida.")
    try:
        profile = extract_candidate_profile_from_pdf(content)
    except Exception as error:
        raise ValueError("No fue posible procesar el PDF.") from error
    candidate_id = str(uuid.uuid4())
    name = profile["name"] or _fallback_candidate_name(original_filename)
    filename = f"cv-{candidate_id}.pdf"
    metadata_filename = f"{filename}.metadata.json"
    s3_key = f"{S3_PREFIX}/{filename}"
    metadata_key = f"{S3_PREFIX}/{metadata_filename}"
    metadata = {"metadataAttributes": {
        "candidate_id": {"value": {"type": "STRING", "stringValue": candidate_id}},
        "candidate_name": {"value": {"type": "STRING", "stringValue": name}},
        "user_sub": {"value": {"type": "STRING", "stringValue": current_user["sub"]}},
    }}
    try:
        s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=content, ContentType="application/pdf")
        s3.put_object(
            Bucket=S3_BUCKET, Key=metadata_key,
            Body=json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
        ingestion = bedrock_agent.start_ingestion_job(
            knowledgeBaseId=KNOWLEDGE_BASE_ID, dataSourceId=DATA_SOURCE_ID
        ).get("ingestionJob", {})
        record = {
            "candidate_id": candidate_id, "owner_id": current_user["sub"], "user_sub": current_user["sub"],
            "name": name, **profile, "filename": filename, "original_filename": original_filename,
            "s3_location": f"s3://{S3_BUCKET}/{s3_key}",
            "metadata_location": f"s3://{S3_BUCKET}/{metadata_key}",
            "ingestion_job_id": ingestion.get("ingestionJobId"),
            "ingestion_status": ingestion.get("status"), "indexed": False,
        }
        save_candidate_record(record)
        return record
    except Exception as error:
        try:
            s3.delete_object(Bucket=S3_BUCKET, Key=s3_key)
            s3.delete_object(Bucket=S3_BUCKET, Key=metadata_key)
        except Exception:
            pass
        raise RuntimeError(_service_error_message(error)) from error


@app.post("/api/candidates/bulk")
async def create_candidates_bulk(
    files: list[UploadFile] = File(...),
    current_user: dict = Depends(get_current_user),
):
    print("BULK_UPLOAD_STARTED", {"count": len(files), "user_sub": current_user.get("sub")})
    if not files:
        raise HTTPException(status_code=400, detail="Debes seleccionar al menos un PDF.")
    if len(files) > 100:
        raise HTTPException(status_code=400, detail="Puedes subir un máximo de 100 PDFs por lote.")
    candidates, errors = [], []
    for file in files:
        original_filename = os.path.basename(file.filename or "")
        print("BULK_FILE_PROCESSING", {"filename": original_filename})
        try:
            candidates.append(await _prepare_bulk_candidate(file, current_user))
            print("BULK_FILE_SUCCESS", {"filename": original_filename})
        except (ValueError, RuntimeError) as error:
            errors.append({"original_filename": original_filename, "error": str(error)})
            print("BULK_FILE_FAILED", {"filename": original_filename, "error": str(error)})
        except Exception:
            errors.append({"original_filename": original_filename, "error": "Error inesperado al procesar el archivo."})
            print("BULK_FILE_FAILED", {"filename": original_filename, "error": "unexpected_error"})
    result = {
        "processed": len(files),
        "successful": len(candidates),
        "failed": len(errors),
        "total": len(files),
        "created": len(candidates),
        "candidates": candidates,
        "errors": errors,
    }
    print("BULK_UPLOAD_COMPLETED", {
        "processed": result["processed"],
        "successful": result["successful"],
        "failed": result["failed"],
    })
    return result


@app.post("/api/candidates"
)
async def create_candidate(
    name: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    if not name.strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "El nombre del candidato "
                "es obligatorio."
            )
        )
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="Debes enviar un archivo."
        )
    extension = os.path.splitext(
        file.filename
    )[1].lower()
    if extension != ".pdf":
        raise HTTPException(
            status_code=400,
            detail=(
                "El CV debe estar en formato PDF."
            )
        )
    candidate_id = str(
        uuid.uuid4()
    )
    filename = (
        f"cv-{candidate_id}.pdf"
    )
    metadata_filename = (
        f"cv-{candidate_id}.pdf.metadata.json"
    )
    s3_key = (
        f"{S3_PREFIX}/{filename}"
    )
    metadata_key = (
        f"{S3_PREFIX}/{metadata_filename}"
    )
    try:
        file_content = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No se pudo leer el PDF: {str(e)}"
            )
        )
    if not file_content:
        raise HTTPException(
            status_code=400,
            detail="El archivo está vacío."
        )
    # ========================================================
    # SUBIR PDF
    # ========================================================
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=file_content,
            ContentType="application/pdf"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Error subiendo CV a S3: {str(e)}"
            )
        )
    # ========================================================
    # METADATA BEDROCK
    # ========================================================
    metadata = {
        "metadataAttributes": {
            "candidate_id": {
                "value": {
                    "type": "STRING",
                    "stringValue": candidate_id
                }
            },
            "candidate_name": {
                "value": {
                    "type": "STRING",
                    "stringValue": name.strip()
                }
            }
        }
    }
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=metadata_key,
            Body=json.dumps(
                metadata,
                ensure_ascii=False
            ).encode("utf-8"),
            ContentType="application/json"
        )
    except Exception as e:
        try:
            s3.delete_object(
                Bucket=S3_BUCKET,
                Key=s3_key
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=(
                "Error creando metadata del candidato: "
                f"{str(e)}"
            )
        )
    # ========================================================
    # INICIAR INGESTION
    # ========================================================
    try:
        ingestion_response = (
            bedrock_agent.start_ingestion_job(
                knowledgeBaseId=KNOWLEDGE_BASE_ID,
                dataSourceId=DATA_SOURCE_ID
            )
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "CV subido correctamente, pero no se pudo "
                "iniciar la ingestion de Bedrock: "
                f"{str(e)}"
            )
        )
    ingestion_job = (
        ingestion_response.get(
            "ingestionJob",
            {}
        )
    )
    ingestion_job_id = (
        ingestion_job.get(
            "ingestionJobId"
        )
    )
    ingestion_status = (
        ingestion_job.get(
            "status"
        )
    )
    # ========================================================
    # GUARDAR CANDIDATO EN DYNAMODB
    # ========================================================
    candidate_record = {
        "candidate_id": candidate_id,
        "owner_id": current_user["sub"],
        "user_sub": current_user["sub"],
        "name": name.strip(),
        "filename": filename,
        "s3_location": (
            f"s3://{S3_BUCKET}/{s3_key}"
        ),
        "metadata_location": (
            f"s3://{S3_BUCKET}/{metadata_key}"
        ),
        "ingestion_job_id": ingestion_job_id,
        "ingestion_status": ingestion_status,
        "indexed": False
    }
    try:
        save_candidate_record(
            candidate_record
        )
    except Exception as e:
        print(
            "ERROR GUARDANDO CANDIDATO EN DYNAMODB:",
            str(e)
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "El CV fue subido e ingestion iniciada, "
                "pero no se pudo guardar el candidato "
                f"en DynamoDB: {str(e)}"
            )
        )
    return {
        "message": "CV uploaded successfully",
        "candidate": {
            "id": candidate_id,
            "name": name.strip()
        },
        "file": filename,
        "metadata_file": metadata_filename,
        "s3_location": (
            f"s3://{S3_BUCKET}/{s3_key}"
        ),
        "metadata_location": (
            f"s3://{S3_BUCKET}/{metadata_key}"
        ),
        "knowledge_base_id": KNOWLEDGE_BASE_ID,
        "data_source_id": DATA_SOURCE_ID,
        "ingestion_job_id": ingestion_job_id,
        "ingestion_status": ingestion_status
    }

# ============================================================
# DOWNLOAD CANDIDATE CV
# ============================================================

@app.get("/api/candidates/{candidate_id}/download"
)
def download_candidate_cv(
    candidate_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:

        candidate = get_candidate_record(
            candidate_id
        )

        if not candidate:
            raise HTTPException(
                status_code=404,
                detail="Candidato no encontrado."
            )

        # ================================================
        # VALIDAR PROPIETARIO
        # ================================================

        if candidate.get(
            "owner_id"
        ) != current_user["sub"]:

            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para acceder a este CV."
            )

        # ================================================
        # OBTENER S3 KEY
        # ================================================

        s3_location = candidate.get(
            "s3_location"
        )

        if not s3_location:
            raise HTTPException(
                status_code=404,
                detail="El CV no tiene ubicación en S3."
            )

        prefix = f"s3://{S3_BUCKET}/"

        if s3_location.startswith(prefix):
            s3_key = s3_location[len(prefix):]
        else:
            s3_key = s3_location

        # ================================================
        # GENERAR URL TEMPORAL
        # ================================================

        download_filename = candidate.get("filename")

        if candidate.get("name"):
            clean_name = (
                candidate["name"]
                .strip()
                .replace(" ", "_")
            )

            download_filename = f"{clean_name}_CV.pdf"

        if not download_filename:
            download_filename = "CV.pdf"


        download_url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": S3_BUCKET,
                "Key": s3_key,
                "ResponseContentType": "application/pdf",
                "ResponseContentDisposition": (
                    f'attachment; filename="{download_filename}"'
                ),
            },
            ExpiresIn=300
        )

        return {
            "download_url": download_url
        }

    except HTTPException:
        raise

    except Exception as e:

        print(
            "ERROR DOWNLOAD CANDIDATE CV:",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="No fue posible generar la descarga del CV."
        )

# ============================================================
# GET CANDIDATE BY ID
# ============================================================
@app.get("/api/candidates/{candidate_id}"
)
def get_candidate(
    candidate_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        candidate = get_candidate_record(
            candidate_id
        )
        if not candidate:
            raise HTTPException(
                status_code=404,
                detail="Candidato no encontrado."
            )
        if candidate.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para acceder a este candidato."
            )
        ingestion_job_id = candidate.get(
            "ingestion_job_id"
        )
        ingestion_status = candidate.get(
            "ingestion_status"
        )
        indexed = candidate.get(
            "indexed",
            False
        )
        # ====================================================
        # ACTUALIZAR ESTADO REAL DE BEDROCK
        # ====================================================
        if ingestion_job_id:
            try:
                response = (
                    bedrock_agent.get_ingestion_job(
                        knowledgeBaseId=KNOWLEDGE_BASE_ID,
                        dataSourceId=DATA_SOURCE_ID,
                        ingestionJobId=ingestion_job_id
                    )
                )
                job = response.get(
                    "ingestionJob",
                    {}
                )
                ingestion_status = job.get(
                    "status",
                    ingestion_status
                )
                indexed = (
                    ingestion_status == "COMPLETE"
                )
                candidate[
                    "ingestion_status"
                ] = ingestion_status
                candidate[
                    "indexed"
                ] = indexed
                save_candidate_record(
                    candidate
                )
            except Exception as ingestion_error:
                print(
                    "WARNING GET CANDIDATE "
                    "INGESTION STATUS:",
                    str(ingestion_error)
                )
        return {
            "candidate_id": candidate.get(
                "candidate_id"
            ),
            "name": candidate.get(
                "name"
            ),
            "filename": candidate.get(
                "filename"
            ),
            "s3_location": candidate.get(
                "s3_location"
            ),
            "metadata_location": candidate.get(
                "metadata_location"
            ),
            "ingestion_job_id": ingestion_job_id,
            "ingestion_status": ingestion_status,
            "indexed": indexed
        }
    except HTTPException:
        raise
    except Exception as e:
        print(
            f"ERROR GET CANDIDATE: {str(e)}"
        )
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ============================================================
# GET JOB BY ID
# ============================================================

@app.get("/api/jobs/{job_id}"
)
def get_job(
    job_id: str,
    current_user: dict = Depends(get_current_user)
):

    job = get_job_record(
        job_id
    )

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Vacante no encontrada."
        )

    validate_job_owner(
        job,
        current_user
    )

    return job

# ============================================================
# LIST CANDIDATES
# ============================================================
@app.get("/api/candidates"
)
def list_candidates(
    current_user: dict = Depends(get_current_user)
):

    try:
        response = candidates_table.scan()
        
        candidates = response.get(
            "Items",
            []
        )

        owner_id = current_user["sub"]

        user_candidates = [
            candidate
            for candidate in candidates
            if candidate.get("owner_id") == owner_id
        ]

        return {
            "candidates": user_candidates
        }

    except Exception as e:
        print(
            f"ERROR LIST CANDIDATES: {str(e)}"
        )
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# DELETE CANDIDATE
# ============================================================

@app.delete("/api/candidates/{candidate_id}"
)
def delete_candidate(
    candidate_id: str,
    current_user: dict = Depends(get_current_user)
):

    try:

        candidate = get_candidate_record(
            candidate_id
        )

        if not candidate:
            raise HTTPException(
                status_code=404,
                detail="Candidato no encontrado."
            )


        if candidate.get(
            "owner_id"
        ) != current_user["sub"]:

            raise HTTPException(
                status_code=403,
                detail="No tienes permiso sobre este candidato."
            )


        # eliminar evaluaciones relacionadas
        evaluations = evaluations_table.query(
            IndexName="candidate-index",
            KeyConditionExpression=
                Key("candidate_id").eq(candidate_id)
        )


        for evaluation in evaluations.get(
            "Items",
            []
        ):

            evaluations_table.delete_item(
                Key={
                    "job_id":
                        evaluation["job_id"],
                    "candidate_id":
                        evaluation["candidate_id"]
                }
            )


        # eliminar registro candidato

        candidates_table.delete_item(
            Key={
                "candidate_id":
                    candidate_id
            }
        )


        # eliminar PDF S3

        if candidate.get(
            "s3_location"
        ):

            bucket = candidate["s3_location"].split("/")[2]

            key = "/".join(
                candidate["s3_location"].split("/")[3:]
            )

            s3.delete_object(
                Bucket=bucket,
                Key=key
            )


        return {
            "message":
                "Candidato eliminado correctamente.",
            "candidate_id":
                candidate_id
        }


    except HTTPException:
        raise


    except Exception as e:

        print(
            f"ERROR DELETE CANDIDATE: {str(e)}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# DELETE JOB
# ============================================================

@app.delete("/api/jobs/{job_id}"
)
def delete_job(
    job_id: str,
    current_user: dict = Depends(get_current_user)
):

    try:

        job = get_job_record(
            job_id
        )


        if not job:
            raise HTTPException(
                status_code=404,
                detail="Vacante no encontrada."
            )


        validate_job_owner(
            job,
            current_user
        )


        # borrar evaluaciones asociadas

        evaluations =  evaluations_table.scan(
            FilterExpression=
                Attr("job_id").eq(job_id)
        )


        for evaluation in evaluations.get(
            "Items",
            []
        ):

            evaluations_table.delete_item(
                Key={
                    "job_id": job_id,
                    "candidate_id": evaluation["candidate_id"]
                }
            )


        # borrar vacante

        jobs_table.delete_item(
            Key={
                "job_id":
                    job_id
            }
        )


        return {
            "message":
                "Vacante eliminada correctamente.",
            "job_id":
                job_id
        }



    except HTTPException:
        raise


    except Exception as e:

        print(
            f"ERROR DELETE JOB: {str(e)}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
# ============================================================
# INGESTION STATUS
# ============================================================
@app.get("/api/candidates/{candidate_id}/ingestion/{ingestion_job_id}"
)
def get_ingestion_status(
    candidate_id: str,
    ingestion_job_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        response = (
            bedrock_agent.get_ingestion_job(
                knowledgeBaseId=KNOWLEDGE_BASE_ID,
                dataSourceId=DATA_SOURCE_ID,
                ingestionJobId=ingestion_job_id
            )
        )
        job = response.get(
            "ingestionJob",
            {}
        )
        status = job.get(
            "status"
        )
        indexed = (
            status == "COMPLETE"
        )
        # ====================================================
        # ACTUALIZAR DYNAMODB
        # ====================================================
        candidate = get_candidate_record(
            candidate_id
        )
        if candidate:
            candidate[
                "ingestion_status"
            ] = status
            candidate[
                "indexed"
            ] = indexed
            save_candidate_record(
                candidate
            )
        return {
            "candidate_id": candidate_id,
            "ingestion_job_id": ingestion_job_id,
            "status": status,
            "indexed": indexed,
            "statistics": job.get(
                "statistics"
            ),
            "failure_reasons": job.get(
                "failureReasons",
                []
            )
        }
    except Exception as e:
        print(
            f"ERROR INGESTION STATUS: {str(e)}"
        )
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# ASK CANDIDATE
# ============================================================
@app.post("/api/candidates/{candidate_id}/ask",
    response_model=AskCandidateResponse
)
def ask_candidate(
    candidate_id: str,
    request: AskCandidateRequest,
    current_user: dict = Depends(get_current_user)
):
    try:
        candidate = get_candidate_record(
            candidate_id
        )
        if not candidate:
            raise HTTPException(
                status_code=404,
                detail="Candidato no encontrado."
            )
        if candidate.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para consultar este candidato."
            )
        results = retrieve_candidate(
            candidate_id=candidate_id,
            question=request.question
        )
        if not results:
            return AskCandidateResponse(
                candidate_id=candidate_id,
                answer=(
                    "No encontré información relevante "
                    "sobre este candidato en su CV."
                ),
                sources=[]
            )
        answer = generate_answer(
            candidate_id=candidate_id,
            question=request.question,
            results=results
        )
        sources = build_sources(
            results
        )
        return AskCandidateResponse(
            candidate_id=candidate_id,
            answer=answer,
            sources=sources
        )
    except HTTPException:
        raise
    except Exception as e:
        print(
            f"ERROR ASK CANDIDATE: {str(e)}"
        )
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# EVALUATE CANDIDATE DIRECT
# ============================================================
@app.post("/api/candidates/{candidate_id}/evaluate",
    response_model=CandidateEvaluation
)
def evaluate_candidate_endpoint(
    candidate_id: str,
    request: EvaluateCandidateRequest,
    current_user: dict = Depends(get_current_user)
):
    try:
        candidate = get_candidate_record(
            candidate_id
        )
        if not candidate:
            raise HTTPException(
                status_code=404,
                detail="Candidato no encontrado."
            )
        results = retrieve_candidate(
            candidate_id=candidate_id,
            question=request.job_description
        )
        evaluation = evaluate_candidate(
            candidate_id=candidate_id,
            job_description=request.job_description,
            results=results
        )
        sources = build_sources(
            results
        )
        return CandidateEvaluation(
            candidate_id=candidate_id,
            match_score=evaluation.get(
                "match_score",
                0
            ),
            recommendation=evaluation.get(
                "recommendation",
                "LOW_MATCH"
            ),
            requirements=evaluation.get(
                "requirements",
                []
            ),
            strengths=evaluation.get(
                "strengths",
                []
            ),
            gaps=evaluation.get(
                "gaps",
                []
            ),
            summary=evaluation.get(
                "summary",
                ""
            ),
            sources=sources
        )
    except HTTPException:
        raise
    except Exception as e:
        print(
            f"ERROR EVALUATING CANDIDATE: {str(e)}"
        )
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# EVALUATE CANDIDATE AGAINST JOB
# ============================================================
@app.post("/api/candidates/{candidate_id}/evaluate-job",
    response_model=CandidateEvaluation
)
def evaluate_candidate_job(
    candidate_id: str,
    request: EvaluateJobRequest,
    current_user: dict = Depends(get_current_user)
):
    try:
        candidate = get_candidate_record(
            candidate_id
        )
        if not candidate:
            raise HTTPException(
                status_code=404,
                detail="Candidato no encontrado."
            )
        job = get_job_record(
            request.job_id
        )
        if not job:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Vacante no encontrada."
                )
            )
        if candidate.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso sobre este candidato."
            )
        validate_job_owner(
            job,
            current_user
        )   
        results = retrieve_candidate(
            candidate_id=candidate_id,
            question=job["description"]
        )
        evaluation = evaluate_candidate(
            candidate_id=candidate_id,
            job_description=job["description"],
            results=results
        )
        # ====================================================
        # GUARDAR EVALUACIÓN EN DYNAMODB
        # ====================================================
        evaluation_record = {
            "job_id": request.job_id,
            "job_title": job.get(
                "title",
                ""
            ),

            "job_description": job.get(
                "description",
                ""
            ),

            "candidate_id": candidate_id,
            "candidate_name": candidate.get(
                "name",
                ""
            ),

            "owner_id": job["owner_id"],

            "status": "COMPLETED",

            "match_score": int(
                evaluation.get(
                    "match_score",
                    0
                )
            ),

            "recommendation": evaluation.get(
                "recommendation",
                "LOW_MATCH"
            ),

            "requirements": json.dumps(
                evaluation.get(
                    "requirements",
                    []
                ),
                ensure_ascii=False
            ),

            "strengths": json.dumps(
                evaluation.get(
                    "strengths",
                    []
                ),
                ensure_ascii=False
            ),

            "gaps": json.dumps(
                evaluation.get(
                    "gaps",
                    []
                ),
                ensure_ascii=False
            ),

            "summary": evaluation.get(
                "summary",
                ""
            )
        }

        save_evaluation_record(
            evaluation_record
        )
        sources = build_sources(
            results
        )
        return CandidateEvaluation(
            candidate_id=candidate_id,
            match_score=evaluation.get(
                "match_score",
                0
            ),
            recommendation=evaluation.get(
                "recommendation",
                "LOW_MATCH"
            ),
            requirements=evaluation.get(
                "requirements",
                []
            ),
            strengths=evaluation.get(
                "strengths",
                []
            ),
            gaps=evaluation.get(
                "gaps",
                []
            ),
            summary=evaluation.get(
                "summary",
                ""
            ),
            sources=sources
        )
    except HTTPException:
        raise
    except Exception as e:
        print(
            f"ERROR EVALUATING JOB: {str(e)}"
        )
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# GET EVALUATIONS BY JOB
# ============================================================
@app.get("/api/jobs/{job_id}/evaluations"
)
def get_job_evaluations(
    job_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:

        job = get_job_record(
            job_id
        )

        if not job:
            raise HTTPException(
                status_code=404,
                detail="Vacante no encontrada."
            )


        validate_job_owner(
            job,
            current_user
        )


        response = evaluations_table.query(
            KeyConditionExpression=
                Key("job_id").eq(job_id)
        )


        evaluations = response.get(
            "Items",
            []
        )

        for item in evaluations:

            item["requirements"] = parse_json_field(
                item.get("requirements", [])
            )

            item["strengths"] = parse_json_field(
                item.get("strengths", [])
            )

            item["gaps"] = parse_json_field(
                item.get("gaps", [])
            )


        evaluations.sort(
            key=lambda x: int(
                x.get(
                    "match_score",
                    0
                )
            ),
            reverse=True
        )


        return {
            "job_id": job_id,
            "job_title": job.get(
                "title",
                ""
            ),
            "total": len(
                evaluations
            ),
            "evaluations": evaluations
        }


    except HTTPException:
        raise


    except Exception as e:

        print(
            f"ERROR GET JOB EVALUATIONS: {str(e)}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# GET EVALUATIONS BY CANDIDATE
# ============================================================
@app.get("/api/candidates/{candidate_id}/evaluations"
)
def get_candidate_evaluations(
    candidate_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:

        candidate = get_candidate_record(
            candidate_id
        )


        if not candidate:
            raise HTTPException(
                status_code=404,
                detail="Candidato no encontrado."
            )


        if candidate.get(
            "owner_id"
        ) != current_user["sub"]:

            raise HTTPException(
                status_code=403,
                detail="No tienes permiso sobre este candidato."
            )


        response = evaluations_table.query(
            IndexName="candidate-index",
            KeyConditionExpression=
                Key("candidate_id").eq(candidate_id)
        )


        evaluations = response.get(
            "Items",
            []
        )

        for item in evaluations:

            item["requirements"] = parse_json_field(
                item.get("requirements", [])
            )

            item["strengths"] = parse_json_field(
                item.get("strengths", [])
            )

            item["gaps"] = parse_json_field(
                item.get("gaps", [])
            )

        return {
            "candidate_id": candidate_id,
            "candidate_name": candidate.get(
                "name",
                ""
            ),
            "total": len(
                evaluations
            ),
            "evaluations": evaluations
        }


    except HTTPException:
        raise


    except Exception as e:

        print(
            f"ERROR GET CANDIDATE EVALUATIONS: {str(e)}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# JOB RANKING
# ============================================================

@app.get("/api/jobs/{job_id}/ranking",
    response_model=JobRankingResponse
)
def get_job_ranking(
    job_id: str,
    min_score: int = 0,
    max_score: int = 100,
    recommendation: str | None = None,
    limit: int | None = None,
    page: int = 1,
    page_size: int = 10,
    current_user: dict = Depends(get_current_user)
):
    try:

        # ====================================================
        # VALIDACIONES
        # ====================================================

        if min_score < 0 or min_score > 100:
            raise HTTPException(
                status_code=400,
                detail="min_score debe estar entre 0 y 100."
            )

        if max_score < 0 or max_score > 100:
            raise HTTPException(
                status_code=400,
                detail="max_score debe estar entre 0 y 100."
            )

        if min_score > max_score:
            raise HTTPException(
                status_code=400,
                detail=(
                    "min_score no puede ser mayor "
                    "que max_score."
                )
            )

        if limit is not None and limit <= 0:
            raise HTTPException(
                status_code=400,
                detail="limit debe ser mayor que 0."
            )

        if page < 1:
            raise HTTPException(
                status_code=400,
                detail="page debe ser mayor o igual a 1."
            )

        if page_size < 1 or page_size > 100:
            raise HTTPException(
                status_code=400,
                detail="page_size debe estar entre 1 y 100."
            )

        # ====================================================
        # NORMALIZAR RECOMMENDATION
        # ====================================================

        if recommendation:

            recommendation = recommendation.upper()

            allowed_recommendations = {
                "STRONG_MATCH",
                "GOOD_MATCH",
                "PARTIAL_MATCH",
                "LOW_MATCH",
                "PENDING"
            }

            if recommendation not in allowed_recommendations:

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "recommendation debe ser "
                        "STRONG_MATCH, GOOD_MATCH, "
                        "PARTIAL_MATCH, LOW_MATCH "
                        "o PENDING."
                    )
                )

        # ====================================================
        # OBTENER VACANTE
        # ====================================================

        job = get_job_record(
            job_id
        )

        if not job:

            raise HTTPException(
                status_code=404,
                detail="Vacante no encontrada."
            )

        # ====================================================
        # VALIDAR PROPIETARIO
        # ====================================================

        validate_job_owner(
            job,
            current_user
        )

        owner_id = current_user["sub"]

        # ====================================================
        # OBTENER TODOS LOS CANDIDATOS DEL USUARIO
        #
        # candidates_table:
        #   PK = candidate_id
        #
        # Por eso NO usamos:
        #
        # candidates_table.query(
        #     Key("owner_id").eq(...)
        # )
        #
        # Usamos scan + FilterExpression.
        # ====================================================

        all_candidates = []

        candidates_response = candidates_table.scan(
            FilterExpression=(
                boto3.dynamodb.conditions.Attr(
                    "owner_id"
                ).eq(
                    owner_id
                )
            )
        )

        all_candidates.extend(
            candidates_response.get(
                "Items",
                []
            )
        )

        # ====================================================
        # PAGINACIÓN CORRECTA DEL SCAN
        # ====================================================

        while candidates_response.get(
            "LastEvaluatedKey"
        ):

            candidates_response = candidates_table.scan(
                FilterExpression=(
                    boto3.dynamodb.conditions.Attr(
                        "owner_id"
                    ).eq(
                        owner_id
                    )
                ),
                ExclusiveStartKey=(
                    candidates_response[
                        "LastEvaluatedKey"
                    ]
                )
            )

            all_candidates.extend(
                candidates_response.get(
                    "Items",
                    []
                )
            )

        print(
            f"RANKING - candidatos encontrados: "
            f"{len(all_candidates)}"
        )

        # ====================================================
        # OBTENER EVALUACIONES DE LA VACANTE
        #
        # evaluations_table:
        #   PK = job_id
        #
        # Por eso Query por job_id es correcto.
        # ====================================================

        evaluations = []

        evaluations_response = evaluations_table.query(
            KeyConditionExpression=(
                boto3.dynamodb.conditions.Key(
                    "job_id"
                ).eq(
                    job_id
                )
            )
        )

        evaluations.extend(
            evaluations_response.get(
                "Items",
                []
            )
        )

        # ====================================================
        # PAGINACIÓN DE EVALUACIONES
        # ====================================================

        while evaluations_response.get(
            "LastEvaluatedKey"
        ):

            evaluations_response = evaluations_table.query(
                KeyConditionExpression=(
                    boto3.dynamodb.conditions.Key(
                        "job_id"
                    ).eq(
                        job_id
                    )
                ),
                ExclusiveStartKey=(
                    evaluations_response[
                        "LastEvaluatedKey"
                    ]
                )
            )

            evaluations.extend(
                evaluations_response.get(
                    "Items",
                    []
                )
            )

        print(
            f"RANKING - evaluaciones encontradas: "
            f"{len(evaluations)}"
        )

        # ====================================================
        # INDEXAR EVALUACIONES POR CANDIDATO
        # ====================================================

        evaluations_by_candidate = {}

        for evaluation in evaluations:

            candidate_id = evaluation.get(
                "candidate_id"
            )

            if not candidate_id:
                continue

            evaluations_by_candidate[
                candidate_id
            ] = evaluation

        print(
            f"RANKING - candidatos evaluados: "
            f"{len(evaluations_by_candidate)}"
        )

        # ====================================================
        # CONSTRUIR RANKING
        # ====================================================

        candidates = []

        for candidate in all_candidates:

            candidate_id = candidate.get(
                "candidate_id"
            )

            if not candidate_id:
                continue

            # =================================================
            # BUSCAR EVALUACIÓN
            # =================================================

            evaluation = evaluations_by_candidate.get(
                candidate_id
            )

            # =================================================
            # CANDIDATO SIN EVALUACIÓN
            # =================================================

            if not evaluation:

                if recommendation == "PENDING":

                    candidates.append(
                        {
                            "candidate_id": candidate_id,

                            "candidate_name": candidate.get(
                                "name",
                                "Unknown"
                            ),

                            "match_score": 0,

                            "recommendation": "PENDING",

                            "strengths": [],

                            "gaps": []
                        }
                    )

                continue

            # =================================================
            # SCORE
            # =================================================

            try:

                match_score = int(
                    evaluation.get(
                        "match_score",
                        0
                    )
                )

            except Exception:

                match_score = 0

            # Mantener score entre 0 y 100.

            match_score = max(
                0,
                min(
                    100,
                    match_score
                )
            )

            # =================================================
            # RECOMMENDATION
            # =================================================

            evaluation_recommendation = (
                evaluation.get(
                    "recommendation",
                    "LOW_MATCH"
                )
            )

            if not evaluation_recommendation:

                evaluation_recommendation = (
                    "LOW_MATCH"
                )

            evaluation_recommendation = str(
                evaluation_recommendation
            ).upper()

            # =================================================
            # FILTRO MIN SCORE
            # =================================================

            if match_score < min_score:
                continue

            # =================================================
            # FILTRO MAX SCORE
            # =================================================

            if match_score > max_score:
                continue

            # =================================================
            # FILTRO RECOMMENDATION
            # =================================================

            if (
                recommendation
                and recommendation != "PENDING"
                and evaluation_recommendation
                != recommendation
            ):
                continue

            # =================================================
            # STRENGTHS
            # =================================================

            strengths_raw = evaluation.get(
                "strengths",
                []
            )

            if isinstance(
                strengths_raw,
                str
            ):

                try:

                    strengths = json.loads(
                        strengths_raw
                    )

                except Exception:

                    strengths = []

            else:

                strengths = strengths_raw

            if not isinstance(
                strengths,
                list
            ):

                strengths = []

            # =================================================
            # GAPS
            # =================================================

            gaps_raw = evaluation.get(
                "gaps",
                []
            )

            if isinstance(
                gaps_raw,
                str
            ):

                try:

                    gaps = json.loads(
                        gaps_raw
                    )

                except Exception:

                    gaps = []

            else:

                gaps = gaps_raw

            if not isinstance(
                gaps,
                list
            ):

                gaps = []

            # =================================================
            # AGREGAR CANDIDATO
            # =================================================

            candidates.append(
                {
                    "candidate_id": candidate_id,

                    "candidate_name": candidate.get(
                        "name",
                        evaluation.get(
                            "candidate_name",
                            "Unknown"
                        )
                    ),

                    "match_score": match_score,

                    "recommendation":
                        evaluation_recommendation,

                    "strengths": strengths,

                    "gaps": gaps
                }
            )

        # ====================================================
        # ORDENAR
        # ====================================================

        candidates.sort(
            key=lambda candidate: (
                candidate["match_score"],
                candidate["candidate_name"].lower()
            ),
            reverse=True
        )

        # ====================================================
        # LIMIT
        # ====================================================

        if limit is not None:

            candidates = candidates[
                :limit
            ]

        # ====================================================
        # TOTAL
        # ====================================================

        total = len(
            candidates
        )

        total_pages = (
            (total + page_size - 1)
            // page_size
            if total > 0
            else 0
        )

        # ====================================================
        # PAGINACIÓN DEL RESULTADO
        # ====================================================

        start = (
            page - 1
        ) * page_size

        end = (
            start + page_size
        )

        paginated_candidates = candidates[
            start:end
        ]

        # ====================================================
        # ASIGNAR RANK
        # ====================================================

        ranked_candidates = []

        for index, candidate in enumerate(
            paginated_candidates,
            start=start + 1
        ):

            ranked_candidates.append(
                CandidateRankingItem(
                    rank=index,

                    candidate_id=candidate[
                        "candidate_id"
                    ],

                    candidate_name=candidate[
                        "candidate_name"
                    ],

                    match_score=candidate[
                        "match_score"
                    ],

                    recommendation=candidate[
                        "recommendation"
                    ],

                    status=candidate.get(
                        "status",
                        "COMPLETED"
                    ),

                    strengths=candidate[
                        "strengths"
                    ],

                    gaps=candidate[
                        "gaps"
                    ]
                )
            )

        # ====================================================
        # LOG FINAL
        # ====================================================

        print(
            f"RANKING COMPLETADO - "
            f"job={job_id} "
            f"total={total} "
            f"page={page} "
            f"page_size={page_size}"
        )

        # ====================================================
        # RESPONSE
        # ====================================================

        return JobRankingResponse(
            job_id=job_id,

            job_title=job.get(
                "title",
                ""
            ),

            page=page,

            page_size=page_size,

            total=total,

            total_pages=total_pages,

            candidates=ranked_candidates
        )

    except HTTPException:
        raise

    except Exception as e:

        print(
            f"ERROR JOB RANKING: {str(e)}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# CANDIDATE JOB EVALUATION DETAIL
# ============================================================
@app.get("/api/jobs/{job_id}/candidates/{candidate_id}",
    response_model=CandidateJobEvaluationResponse
)
def get_candidate_job_evaluation(
    job_id: str,
    candidate_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:

        # ====================================================
        # OBTENER JOB
        # ====================================================
        job = get_job_record(
            job_id
        )

        if not job:
            raise HTTPException(
                status_code=404,
                detail="Vacante no encontrada."
            )

        validate_job_owner(
            job,
            current_user
        )

        # ====================================================
        # OBTENER CANDIDATO
        # ====================================================
        candidate = get_candidate_record(
            candidate_id
        )

        if not candidate:
            raise HTTPException(
                status_code=404,
                detail="Candidato no encontrado."
            )

        # ====================================================
        # OBTENER EVALUACIÓN
        # ====================================================
        response = evaluations_table.get_item(
            Key={
                "job_id": job_id,
                "candidate_id": candidate_id
            }
        )

        evaluation = response.get(
            "Item"
        )

        if not evaluation:
            raise HTTPException(
                status_code=404,
                detail=(
                    "El candidato todavía no ha sido "
                    "evaluado para esta vacante."
                )
            )

        # ====================================================
        # PARSE REQUIREMENTS
        # ====================================================
        requirements_raw = evaluation.get(
            "requirements",
            "[]"
        )

        try:

            requirements = json.loads(
                requirements_raw
            )

        except Exception:

            requirements = []

        if not isinstance(
            requirements,
            list
        ):
            requirements = []

        # ====================================================
        # PARSE STRENGTHS
        # ====================================================
        strengths_raw = evaluation.get(
            "strengths",
            "[]"
        )

        try:

            strengths = json.loads(
                strengths_raw
            )

        except Exception:

            strengths = []

        if not isinstance(
            strengths,
            list
        ):
            strengths = []

        # ====================================================
        # PARSE GAPS
        # ====================================================
        gaps_raw = evaluation.get(
            "gaps",
            "[]"
        )

        try:

            gaps = json.loads(
                gaps_raw
            )

        except Exception:

            gaps = []

        if not isinstance(
            gaps,
            list
        ):
            gaps = []

        # ====================================================
        # RESPONSE
        # ====================================================
        return CandidateJobEvaluationResponse(
            job_id=job_id,
            candidate_id=candidate_id,
            candidate_name=candidate.get(
                "name",
                "Unknown"
            ),
            candidate_filename=candidate.get(
                "filename",
                ""
            ),
            match_score=int(
                evaluation.get(
                    "match_score",
                    0
                )
            ),
            recommendation=evaluation.get(
                "recommendation",
                "LOW_MATCH"
            ),
            requirements=requirements,
            strengths=strengths,
            gaps=gaps,
            summary=evaluation.get(
                "summary",
                ""
            )
        )

    except HTTPException:
        raise

    except Exception as e:

        print(
            f"ERROR GET CANDIDATE EVALUATION: {str(e)}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# JOB SUMMARY
# ============================================================
@app.get("/api/jobs/{job_id}/summary",
    response_model=JobSummaryResponse
)
def get_job_summary(
    job_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:

        # ====================================================
        # BUSCAR VACANTE
        # ====================================================
        job = get_job_record(
            job_id
        )

        if not job:
            raise HTTPException(
                status_code=404,
                detail="Vacante no encontrada."
            )

        validate_job_owner(
            job,
            current_user
        )

        # ====================================================
        # OBTENER EVALUACIONES
        # ====================================================
        response = evaluations_table.query(
            KeyConditionExpression=(
                boto3.dynamodb.conditions.Key(
                    "job_id"
                ).eq(job_id)
            )
        )

        evaluations = response.get(
            "Items",
            []
        )

        # ====================================================
        # CONTADORES
        # ====================================================
        evaluated_candidates = 0
        failed_candidates = 0
        pending_candidates = 0

        strong_matches = 0
        partial_matches = 0
        low_matches = 0

        scores = []

        # IMPORTANTE:
        # Esta es la variable que usamos dentro del for
        top_evaluation = None

        # ====================================================
        # ANALIZAR EVALUACIONES
        # ====================================================
        for evaluation in evaluations:

            status = evaluation.get(
                "status",
                "COMPLETED"
            )

            # -----------------------------------------------
            # STATUS
            # -----------------------------------------------
            if status == "COMPLETED":

                evaluated_candidates += 1

            elif status == "FAILED":

                failed_candidates += 1

            elif status == "PENDING":

                pending_candidates += 1

            else:

                pending_candidates += 1

            # Solo evaluaciones completadas
            if status != "COMPLETED":
                continue

            # -----------------------------------------------
            # MATCH SCORE
            # -----------------------------------------------
            match_score = int(
                evaluation.get(
                    "match_score",
                    0
                )
            )

            scores.append(
                match_score
            )

            # -----------------------------------------------
            # RECOMMENDATION
            # -----------------------------------------------
            recommendation = evaluation.get(
                "recommendation",
                "LOW_MATCH"
            )

            if recommendation == "STRONG_MATCH":

                strong_matches += 1

            elif recommendation == "PARTIAL_MATCH":

                partial_matches += 1

            else:

                low_matches += 1

            # -----------------------------------------------
            # TOP CANDIDATE
            # -----------------------------------------------
            if (
                top_evaluation is None
                or match_score
                > int(
                    top_evaluation.get(
                        "match_score",
                        0
                    )
                )
            ):
                top_evaluation = evaluation

        # ====================================================
        # SCORE PROMEDIO
        # ====================================================
        if scores:

            average_score = round(
                sum(scores)
                / len(scores),
                1
            )

        else:

            average_score = 0.0

        # ====================================================
        # TOP CANDIDATE
        # ====================================================
        top_candidate = None

        if top_evaluation:

            top_candidate_id = (
                top_evaluation[
                    "candidate_id"
                ]
            )

            candidate = get_candidate_record(
                top_candidate_id
            )

            top_candidate = (
                JobSummaryTopCandidate(
                    candidate_id=(
                        top_candidate_id
                    ),
                    candidate_name=candidate.get(
                        "name",
                        "Unknown"
                    ),
                    match_score=int(
                        top_evaluation.get(
                            "match_score",
                            0
                        )
                    ),
                    recommendation=(
                        top_evaluation.get(
                            "recommendation",
                            "LOW_MATCH"
                        )
                    )
                )
            )

        # ====================================================
        # TOTAL CANDIDATOS
        # ====================================================

        # Las evaluaciones están asociadas directamente
        # a la vacante mediante job_id.
        #
        # Por eso el total de candidatos de esta vacante
        # debe calcularse desde evaluations_table y no
        # desde candidates_table.

        total_candidates = len(
            evaluations
        )

        # ====================================================
        # RESPONSE
        # ====================================================
        return JobSummaryResponse(
            job_id=job_id,
            job_title=job["title"],

            total_candidates=(
                total_candidates
            ),

            evaluated_candidates=(
                evaluated_candidates
            ),

            pending_candidates=(
                pending_candidates
            ),

            failed_candidates=(
                failed_candidates
            ),

            strong_matches=(
                strong_matches
            ),

            partial_matches=(
                partial_matches
            ),

            low_matches=(
                low_matches
            ),

            average_score=(
                average_score
            ),

            top_candidate=(
                top_candidate
            )
        )

    except HTTPException:
        raise

    except Exception as e:

        print(
            f"ERROR JOB SUMMARY: {str(e)}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ============================================================
# JOB CANDIDATES
# ============================================================
@app.get("/api/jobs/{job_id}/candidates"
)
def get_job_candidates(
    job_id: str,
    min_score: int = 0,
    recommendation: str | None = None,
    page: int = 1,
    page_size: int = 10,
    current_user: dict = Depends(get_current_user)
):
    try:

        # ====================================================
        # VALIDAR VACANTE
        # ====================================================
        job = get_job_record(
            job_id
        )

        if not job:
            raise HTTPException(
                status_code=404,
                detail="Vacante no encontrada."
            )

        validate_job_owner(
            job,
            current_user
        )

        # ====================================================
        # VALIDAR PAGINACIÓN
        # ====================================================
        if page < 1:
            raise HTTPException(
                status_code=400,
                detail="page debe ser mayor o igual a 1."
            )

        if page_size < 1 or page_size > 100:
            raise HTTPException(
                status_code=400,
                detail="page_size debe estar entre 1 y 100."
            )

        # ====================================================
        # VALIDAR SCORE
        # ====================================================
        if min_score < 0 or min_score > 100:
            raise HTTPException(
                status_code=400,
                detail="min_score debe estar entre 0 y 100."
            )

        # ====================================================
        # QUERY DYNAMODB
        # ====================================================
        response = evaluations_table.query(
            KeyConditionExpression=(
                boto3.dynamodb.conditions.Key(
                    "job_id"
                ).eq(job_id)
            )
        )

        evaluations = response.get(
            "Items",
            []
        )

        candidates = []

        # ====================================================
        # PROCESAR EVALUACIONES
        # ====================================================
        for evaluation in evaluations:

            match_score = int(
                evaluation.get(
                    "match_score",
                    0
                )
            )

            current_recommendation = evaluation.get(
                "recommendation",
                "LOW_MATCH"
            )

            # -----------------------------------------------
            # FILTRO SCORE
            # -----------------------------------------------
            if match_score < min_score:
                continue

            # -----------------------------------------------
            # FILTRO RECOMMENDATION
            # -----------------------------------------------
            if (
                recommendation
                and current_recommendation
                != recommendation
            ):
                continue

            candidate_id = evaluation.get(
                "candidate_id"
            )

            if not candidate_id:
                continue

            # -----------------------------------------------
            # OBTENER CANDIDATO
            # -----------------------------------------------
            candidate = get_candidate_record(
                candidate_id
            )

            if not candidate:
                continue

            # -----------------------------------------------
            # STRENGTHS
            # -----------------------------------------------
            strengths = evaluation.get(
                "strengths",
                []
            )

            if isinstance(
                strengths,
                str
            ):
                try:
                    strengths = json.loads(
                        strengths
                    )
                except Exception:
                    strengths = []

            # -----------------------------------------------
            # GAPS
            # -----------------------------------------------
            gaps = evaluation.get(
                "gaps",
                []
            )

            if isinstance(
                gaps,
                str
            ):
                try:
                    gaps = json.loads(
                        gaps
                    )
                except Exception:
                    gaps = []

            # -----------------------------------------------
            # AGREGAR CANDIDATO
            # -----------------------------------------------
            candidates.append(
                {
                    "candidate_id": candidate_id,

                    "candidate_name": candidate.get(
                        "name",
                        "Unknown"
                    ),

                    "match_score": match_score,

                    "recommendation": (
                        current_recommendation
                    ),

                    "strengths": strengths,

                    "gaps": gaps
                }
            )

        # ====================================================
        # ORDENAR
        # ====================================================
        candidates.sort(
            key=lambda candidate: (
                candidate["match_score"],
                candidate["candidate_name"]
            ),
            reverse=True
        )

        # ====================================================
        # TOTAL
        # ====================================================
        total = len(
            candidates
        )

        # ====================================================
        # PAGINACIÓN
        # ====================================================
        total_pages = (
            (total + page_size - 1)
            // page_size
        )

        start = (
            (page - 1)
            * page_size
        )

        end = (
            start
            + page_size
        )

        paginated_candidates = (
            candidates[
                start:end
            ]
        )

        # ====================================================
        # AGREGAR RANK
        # ====================================================
        for index, candidate in enumerate(
            paginated_candidates,
            start=start + 1
        ):
            candidate["rank"] = index

        # ====================================================
        # RESPONSE
        # ====================================================
        return {
            "job_id": job_id,

            "job_title": job[
                "title"
            ],

            "page": page,

            "page_size": page_size,

            "total": total,

            "total_pages": total_pages,

            "candidates": (
                paginated_candidates
            )
        }

    except HTTPException:
        raise

    except Exception as e:

        print(
            f"ERROR JOB CANDIDATES: {str(e)}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# CANDIDATE EVALUATION EXPLANATION
# ============================================================
@app.get("/api/jobs/{job_id}/candidates/{candidate_id}/explanation"
)
def get_candidate_explanation(
    job_id: str,
    candidate_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:

        # ====================================================
        # VALIDAR VACANTE
        # ====================================================
        job = get_job_record(
            job_id
        )

        if not job:
            raise HTTPException(
                status_code=404,
                detail="Vacante no encontrada."
            )

        validate_job_owner(
            job,
            current_user
        )

        # ====================================================
        # VALIDAR CANDIDATO
        # ====================================================
        candidate = get_candidate_record(
            candidate_id
        )

        if not candidate:
            raise HTTPException(
                status_code=404,
                detail="Candidato no encontrado."
            )

        # ====================================================
        # BUSCAR EVALUACIÓN
        # ====================================================
        response = evaluations_table.get_item(
            Key={
                "job_id": job_id,
                "candidate_id": candidate_id
            }
        )

        evaluation = response.get(
            "Item"
        )

        if not evaluation:
            raise HTTPException(
                status_code=404,
                detail=(
                    "El candidato todavía no ha sido "
                    "evaluado para esta vacante."
                )
            )

        # ====================================================
        # REQUIREMENTS
        # ====================================================
        requirements = evaluation.get(
            "requirements",
            []
        )

        if isinstance(
            requirements,
            str
        ):
            try:
                requirements = json.loads(
                    requirements
                )
            except Exception:
                requirements = []

        # ====================================================
        # STRENGTHS
        # ====================================================
        strengths = evaluation.get(
            "strengths",
            []
        )

        if isinstance(
            strengths,
            str
        ):
            try:
                strengths = json.loads(
                    strengths
                )
            except Exception:
                strengths = []

        # ====================================================
        # GAPS
        # ====================================================
        gaps = evaluation.get(
            "gaps",
            []
        )

        if isinstance(
            gaps,
            str
        ):
            try:
                gaps = json.loads(
                    gaps
                )
            except Exception:
                gaps = []

        # ====================================================
        # CLASIFICAR REQUIREMENTS
        # ====================================================
        matched_requirements = []
        partial_requirements = []
        missing_requirements = []

        for requirement in requirements:

            status = requirement.get(
                "status",
                "MISSING"
            )

            if status == "MATCH":

                matched_requirements.append(
                    requirement
                )

            elif status == "PARTIAL":

                partial_requirements.append(
                    requirement
                )

            else:

                missing_requirements.append(
                    requirement
                )

        # ====================================================
        # SCORE
        # ====================================================
        match_score = int(
            evaluation.get(
                "match_score",
                0
            )
        )

        recommendation = evaluation.get(
            "recommendation",
            "LOW_MATCH"
        )

        # ====================================================
        # EXPLICACIÓN
        # ====================================================
        total_requirements = len(
            requirements
        )

        matched_count = len(
            matched_requirements
        )

        partial_count = len(
            partial_requirements
        )

        missing_count = len(
            missing_requirements
        )

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
            f"explícita para "
            f"{missing_count}."
        )

        # ====================================================
        # RESPONSE
        # ====================================================
        return {
            "job_id": job_id,

            "job_title": job.get(
                "title",
                "Unknown"
            ),

            "candidate_id": candidate_id,

            "candidate_name": candidate.get(
                "name",
                "Unknown"
            ),

            "match_score": match_score,

            "recommendation": recommendation,

            "explanation": explanation,

            "matched_requirements": (
                matched_requirements
            ),

            "partial_requirements": (
                partial_requirements
            ),

            "missing_requirements": (
                missing_requirements
            ),

            "key_strengths": strengths,

            "main_gaps": gaps,

            "summary": evaluation.get(
                "summary",
                ""
            )
        }

    except HTTPException:
        raise

    except Exception as e:

        print(
            f"ERROR CANDIDATE EXPLANATION: {str(e)}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ============================================================
# COMPARE CANDIDATES
# ============================================================

@app.get("/api/jobs/{job_id}/compare",
    response_model=CandidateComparisonResponse
)
def compare_candidates(
    job_id: str,
    candidate_ids: str,
    current_user: dict = Depends(get_current_user)
):
    try:

        # ====================================================
        # BUSCAR VACANTE
        # ====================================================

        job = get_job_record(
            job_id
        )

        if not job:
            raise HTTPException(
                status_code=404,
                detail="Vacante no encontrada."
            )

        validate_job_owner(
            job,
            current_user
        )

        # ====================================================
        # CONVERTIR IDS
        # ====================================================

        ids = [
            candidate_id.strip()
            for candidate_id in candidate_ids.split(",")
            if candidate_id.strip()
        ]

        if not ids:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Debe proporcionar al menos un candidate_id."
                )
            )

        # ====================================================
        # VALIDAR CANTIDAD
        # ====================================================

        if len(ids) > 5:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Máximo 5 candidatos por comparación."
                )
            )

        # ====================================================
        # OBTENER CANDIDATOS
        #
        # IMPORTANTE:
        # candidates_table tiene candidate_id como
        # partition key, por lo que NO podemos hacer:
        #
        # query(Key("owner_id").eq(...))
        #
        # Usamos scan para filtrar por owner_id.
        # ====================================================

        candidates_response = candidates_table.scan(
            FilterExpression=(
                boto3.dynamodb.conditions.Attr(
                    "owner_id"
                ).eq(
                    current_user["sub"]
                )
            )
        )

        all_candidates = candidates_response.get(
            "Items",
            []
        )

        # ====================================================
        # INDEXAR CANDIDATOS POR ID
        # ====================================================

        candidates_by_id = {
            candidate.get("candidate_id"): candidate
            for candidate in all_candidates
            if candidate.get("candidate_id")
        }

        # ====================================================
        # OBTENER EVALUACIONES DE ESTA VACANTE
        # ====================================================

        evaluations_response = evaluations_table.query(
            KeyConditionExpression=(
                boto3.dynamodb.conditions.Key(
                    "job_id"
                ).eq(
                    job_id
                )
            )
        )

        evaluations = evaluations_response.get(
            "Items",
            []
        )

        # ====================================================
        # MAPEAR EVALUACIONES POR CANDIDATO
        # ====================================================

        evaluations_by_candidate = {}

        for evaluation in evaluations:

            candidate_id = evaluation.get(
                "candidate_id"
            )

            if not candidate_id:
                continue

            evaluations_by_candidate[
                candidate_id
            ] = evaluation

        # ====================================================
        # CONSTRUIR COMPARACIÓN
        # ====================================================

        candidates = []

        for candidate_id in ids:

            # =================================================
            # VERIFICAR CANDIDATO
            # =================================================

            candidate = candidates_by_id.get(
                candidate_id
            )

            if not candidate:
                continue

            # =================================================
            # VERIFICAR EVALUACIÓN
            # =================================================

            evaluation = evaluations_by_candidate.get(
                candidate_id
            )

            if not evaluation:
                continue

            # =================================================
            # PARSEAR STRENGTHS
            # =================================================

            strengths_raw = evaluation.get(
                "strengths",
                []
            )

            if isinstance(
                strengths_raw,
                str
            ):
                try:
                    strengths = json.loads(
                        strengths_raw
                    )
                except Exception:
                    strengths = []
            else:
                strengths = strengths_raw

            if not isinstance(
                strengths,
                list
            ):
                strengths = []

            # =================================================
            # PARSEAR GAPS
            # =================================================

            gaps_raw = evaluation.get(
                "gaps",
                []
            )

            if isinstance(
                gaps_raw,
                str
            ):
                try:
                    gaps = json.loads(
                        gaps_raw
                    )
                except Exception:
                    gaps = []
            else:
                gaps = gaps_raw

            if not isinstance(
                gaps,
                list
            ):
                gaps = []

            # =================================================
            # SCORE
            # =================================================

            try:

                match_score = int(
                    evaluation.get(
                        "match_score",
                        0
                    )
                )

            except (
                TypeError,
                ValueError
            ):

                match_score = 0

            # =================================================
            # RECOMMENDATION
            # =================================================

            recommendation = evaluation.get(
                "recommendation",
                "LOW_MATCH"
            )

            if not recommendation:
                recommendation = "LOW_MATCH"

            recommendation = str(
                recommendation
            ).upper()

            # =================================================
            # AGREGAR
            # =================================================

            candidates.append(
                CandidateComparisonItem(
                    candidate_id=candidate_id,

                    candidate_name=candidate.get(
                        "name",
                        "Unknown"
                    ),

                    match_score=match_score,

                    recommendation=recommendation,

                    strengths=strengths,

                    gaps=gaps
                )
            )

        # ====================================================
        # VALIDAR RESULTADOS
        # ====================================================

        if not candidates:

            raise HTTPException(
                status_code=404,
                detail=(
                    "No se encontraron evaluaciones "
                    "para los candidatos indicados."
                )
            )

        # ====================================================
        # ORDENAR POR SCORE
        # ====================================================

        candidates.sort(
            key=lambda candidate: (
                candidate.match_score
            ),
            reverse=True
        )

        # ====================================================
        # ASIGNAR RANK
        # ====================================================

        for index, candidate in enumerate(
            candidates,
            start=1
        ):

            # CandidateComparisonItem probablemente
            # no tiene rank, por eso no modificamos
            # el modelo aquí.
            pass

        # ====================================================
        # GANADOR
        # ====================================================

        winner = candidates[0]

        # ====================================================
        # RESPONSE
        # ====================================================

        return CandidateComparisonResponse(
            job_id=job_id,

            job_title=job.get(
                "title",
                ""
            ),

            candidates=candidates,

            winner=winner
        )

    # ========================================================
    # HTTP ERRORS
    # ========================================================

    except HTTPException:
        raise

    # ========================================================
    # UNEXPECTED ERRORS
    # ========================================================

    except Exception as e:

        print(
            "ERROR COMPARING CANDIDATES: "
            f"{str(e)}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# CANDIDATE REQUIREMENTS
# ============================================================
@app.get("/api/jobs/{job_id}/candidates/{candidate_id}/requirements",
    response_model=CandidateRequirementsResponse
)
def get_candidate_requirements(
    job_id: str,
    candidate_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:

        # ====================================================
        # BUSCAR VACANTE
        # ====================================================
        job = get_job_record(
            job_id
        )

        if not job:
            raise HTTPException(
                status_code=404,
                detail="Vacante no encontrada."
            )

        validate_job_owner(
            job,
            current_user
        )

        # ====================================================
        # BUSCAR CANDIDATO
        # ====================================================
        candidate = get_candidate_record(
            candidate_id
        )

        if not candidate:
            raise HTTPException(
                status_code=404,
                detail="Candidato no encontrado."
            )

        # ====================================================
        # BUSCAR EVALUACIÓN
        # ====================================================
        response = evaluations_table.get_item(
            Key={
                "job_id": job_id,
                "candidate_id": candidate_id
            }
        )

        evaluation = response.get(
            "Item"
        )

        if not evaluation:
            raise HTTPException(
                status_code=404,
                detail=(
                    "El candidato todavía no ha sido "
                    "evaluado para esta vacante."
                )
            )

        # ====================================================
        # REQUIREMENTS
        # ====================================================
        requirements_raw = evaluation.get(
            "requirements",
            "[]"
        )

        try:

            requirements = (
                json.loads(
                    requirements_raw
                )
                if isinstance(
                    requirements_raw,
                    str
                )
                else requirements_raw
            )

        except Exception:

            requirements = []

        # ====================================================
        # NORMALIZAR REQUIREMENTS
        # ====================================================
        normalized_requirements = []

        for requirement in requirements:

            normalized_requirements.append(
                CandidateRequirementItem(
                    requirement=(
                        requirement.get(
                            "requirement",
                            ""
                        )
                    ),

                    status=(
                        requirement.get(
                            "status",
                            "MISSING"
                        )
                    ),

                    evidence=(
                        requirement.get(
                            "evidence"
                        )
                    )
                )
            )

        # ====================================================
        # RESPONSE
        # ====================================================
        return CandidateRequirementsResponse(

            job_id=job_id,

            job_title=job[
                "title"
            ],

            candidate_id=candidate_id,

            candidate_name=candidate.get(
                "name",
                "Unknown"
            ),

            match_score=int(
                evaluation.get(
                    "match_score",
                    0
                )
            ),

            recommendation=evaluation.get(
                "recommendation",
                "LOW_MATCH"
            ),

            requirements=(
                normalized_requirements
            )
        )

    except HTTPException:
        raise

    except Exception as e:

        print(
            f"ERROR CANDIDATE REQUIREMENTS: {str(e)}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# DEBUG RETRIEVE
# ============================================================
@app.get("/api/debug/retrieve/{candidate_id}"
)
def debug_retrieve(
    candidate_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        results = retrieve_candidate(
            candidate_id=candidate_id,
            question=(
                "Python AWS Kubernetes "
                "APIs REST desarrollo backend"
            )
        )
        return {
            "candidate_id": candidate_id,
            "count": len(
                results
            ),
            "results": results
        }
    except Exception as e:
        print(
            f"ERROR DEBUG RETRIEVE: {str(e)}"
        )
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
# CI/CD trigger test

# ============================================================
# AUTH CONFIRMATION
# ============================================================

@app.post("/api/auth/confirm"
)
def confirm_registration(
    email: str,
    confirmation_code: str
):

    result = confirm_user(
        email,
        confirmation_code
    )

    if result.get("error"):

        raise HTTPException(
            status_code=400,
            detail=result["error"]
        )

    return result