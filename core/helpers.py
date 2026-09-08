import json

from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key, Attr

from core.aws_clients import (
    candidates_table,
    jobs_table,
    evaluations_table,
    job_candidates_table,
    rankings_table,
)
from core.models import Source
from core.config import logger


# ============================================================
# JSON HELPERS
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


def invoke_json_prompt(chain, payload: dict, description: str):
    response = chain.invoke(payload)
    raw_content = response.content
    cleaned_content = clean_json(raw_content)
    try:
        return json.loads(cleaned_content)
    except json.JSONDecodeError as first_error:
        print(f"JSON inválido en {description}.")
        print(f"Primer error: {first_error}")
        print(f"Respuesta recibida: {raw_content}")

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


def parse_json_field(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


# ============================================================
# DYNAMODB HELPERS
# ============================================================


def get_candidate_record(candidate_id: str):
    response = candidates_table.get_item(Key={"candidate_id": candidate_id})
    return response.get("Item")


def get_job_record(job_id: str):
    response = jobs_table.get_item(Key={"job_id": job_id})
    return response.get("Item")


def validate_job_owner(job: dict, current_user: dict):
    if job.get("owner_id") != current_user["sub"]:
        raise Exception("FORBIDDEN")


def save_candidate_record(candidate: dict):
    candidates_table.put_item(Item=candidate)


def save_job_record(job: dict):
    jobs_table.put_item(Item=job)


def save_evaluation_record(evaluation: dict):
    evaluations_table.put_item(Item=evaluation)


def assign_candidate_to_job(job_id: str, candidate_id: str, owner_id: str):
    job_candidates_table.put_item(
        Item={
            "job_id": job_id,
            "candidate_id": candidate_id,
            "owner_id": owner_id,
            "status": "PENDING_EVALUATION",
            "assigned_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def get_job_candidate_ids(job_id: str, owner_id: str) -> set[str]:
    response = job_candidates_table.query(
        KeyConditionExpression=Key("job_id").eq(job_id),
        FilterExpression=Attr("owner_id").eq(owner_id),
    )
    return {
        item["candidate_id"]
        for item in response.get("Items", [])
        if item.get("candidate_id")
    }


def get_owned_candidate_ids(owner_id: str) -> set[str]:
    ids = set()
    scan_kwargs = {"FilterExpression": Attr("owner_id").eq(owner_id)}
    while True:
        response = candidates_table.scan(**scan_kwargs)
        ids.update(
            item["candidate_id"]
            for item in response.get("Items", [])
            if item.get("candidate_id")
        )
        if not response.get("LastEvaluatedKey"):
            return ids
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]


# ============================================================
# RANKING METADATA
# ============================================================


def get_ranking_metadata(job_id: str) -> dict | None:
    try:
        response = rankings_table.get_item(Key={"job_id": job_id})
        return response.get("Item")
    except Exception as error:
        logger.exception(
            "ERROR GETTING RANKING METADATA job_id=%s: %s", job_id, error
        )
        raise


def save_ranking_metadata(job_id: str, version: int):
    now = datetime.now(timezone.utc).isoformat()
    try:
        rankings_table.put_item(
            Item={
                "job_id": job_id,
                "ranking_generated_at": now,
                "ranking_version": version,
            }
        )
    except Exception as error:
        logger.exception(
            "ERROR SAVING RANKING METADATA job_id=%s: %s", job_id, error
        )
        raise


def get_new_candidate_ids(
    job_id: str, owner_id: str, since: str
) -> set[str]:
    response = job_candidates_table.query(
        KeyConditionExpression=Key("job_id").eq(job_id),
        FilterExpression=(
            Attr("owner_id").eq(owner_id) & Attr("assigned_at").gt(since)
        ),
    )
    return {
        item["candidate_id"]
        for item in response.get("Items", [])
        if item.get("candidate_id")
    }


# ============================================================
# BUILD SOURCES
# ============================================================


def build_sources(results: list) -> list[Source]:
    sources_dict = {}
    for result in results:
        location = result.get("location", {})
        s3_location = location.get("s3Location", {})
        uri = s3_location.get("uri")
        metadata = result.get("metadata", {})
        page = metadata.get("x-amz-bedrock-kb-document-page-number")
        score = result.get("score", 0)
        try:
            score = float(score or 0)
        except Exception:
            score = 0
        try:
            page_value = int(page) if page is not None else None
        except Exception:
            page_value = None
        key = (uri, page_value)
        if key not in sources_dict or score > sources_dict[key].score:
            sources_dict[key] = Source(file=uri, score=score, page=page_value)
    return list(sources_dict.values())
