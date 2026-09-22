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


def invoke_json_prompt(chain, payload: dict, description: str):
    """Invoke a LangChain chain with JSON output and automatic retry.

    Performs up to two attempts:
    1. First attempt with original payload
    2. If JSON decode fails, retry with strict instruction

    Args:
        chain: LangChain chain to invoke
        payload: Input payload for the chain
        description: Description for error logging

    Returns:
        Parsed JSON dict

    Raises:
        ValueError: If both attempts produce invalid JSON
    """
    response = chain.invoke(payload)
    raw_content = response.content
    cleaned_content = clean_json(raw_content)
    try:
        return json.loads(cleaned_content)
    except json.JSONDecodeError as first_error:
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