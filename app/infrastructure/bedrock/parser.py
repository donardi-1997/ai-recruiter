"""JSON parsing utilities for Bedrock LLM responses.

Contains the canonical JSON cleaning and retry logic.
"""

import json
import logging

logger = logging.getLogger(__name__)


def clean_json(content: str) -> str:
    """Clean and extract JSON from LLM response.

    Handles various response formats:
    - Raw JSON
    - ```json fenced code blocks
    - ``` generic code blocks
    - Text with JSON embedded in prose

    Args:
        content: Raw LLM response content

    Returns:
        Cleaned JSON string

    Raises:
        ValueError: If no valid JSON object can be extracted
    """
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
        raise ValueError("MODEL_JSON_OBJECT_NOT_FOUND")
    end = content.rfind("}")
    if end == -1 or end < start:
        raise ValueError("MODEL_JSON_INCOMPLETE")
    return content[start : end + 1].strip()


def _parse_json_response(content: str) -> dict:
    """Parse one model response without including its content in failures."""
    try:
        parsed = json.loads(clean_json(content))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("MODEL_JSON_INVALID") from exc
    if not isinstance(parsed, dict):
        raise ValueError("MODEL_JSON_NOT_OBJECT")
    return parsed


def invoke_json_prompt(chain, payload: dict, description: str):
    """Invoke a JSON-producing chain with one safe automatic retry."""
    response = chain.invoke(payload)
    raw_content = response.content
    try:
        return _parse_json_response(raw_content)
    except ValueError as first_error:
        logger.error(
            "JSON invalido en %s: %s (response_chars=%d)",
            description,
            first_error,
            len(str(raw_content or "")),
        )

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
    try:
        return _parse_json_response(retry_raw_content)
    except ValueError as second_error:
        logger.error(
            "Segundo JSON invalido en %s: %s (response_chars=%d)",
            description,
            second_error,
            len(str(retry_raw_content or "")),
        )
        raise ValueError(
            f"MODEL_JSON_INVALID_AFTER_RETRY:{description}"
        ) from second_error