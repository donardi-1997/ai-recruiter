"""Bedrock infrastructure package.

Provides AWS Bedrock integration components for the AI Recruiter.
"""

from app.infrastructure.bedrock.config import (
    AWS_REGION,
    BEDROCK_AWS_PROFILE,
    KNOWLEDGE_BASE_ID,
    MODEL_ID,
    MODEL_TEMPERATURE,
    NUMBER_OF_RESULTS,
)

from app.infrastructure.bedrock.session import get_bedrock_session, get_cached_session
from app.infrastructure.bedrock.clients import (
    bedrock_agent_runtime,
    bedrock_runtime,
    llm,
    get_bedrock_agent_runtime,
    get_bedrock_runtime,
    get_llm,
)
from app.infrastructure.bedrock.parser import clean_json, invoke_json_prompt
from app.infrastructure.bedrock.prompts import (
    CANDIDATE_EVALUATION_PROMPT,
    REQUIREMENT_EXTRACTION_PROMPT,
)
from app.infrastructure.bedrock.retriever import retrieve_candidate


def evaluate_candidate(*args, **kwargs):
    """Lazily load the evaluator to keep package initialization cycle-free."""
    from app.infrastructure.bedrock.evaluator import evaluate_candidate as _evaluate_candidate

    return _evaluate_candidate(*args, **kwargs)


__all__ = [
    # Config
    "AWS_REGION",
    "BEDROCK_AWS_PROFILE",
    "KNOWLEDGE_BASE_ID",
    "MODEL_ID",
    "MODEL_TEMPERATURE",
    "NUMBER_OF_RESULTS",
    # Session
    "get_bedrock_session",
    "get_cached_session",
    # Clients
    "bedrock_agent_runtime",
    "bedrock_runtime",
    "llm",
    "get_bedrock_agent_runtime",
    "get_bedrock_runtime",
    "get_llm",
    # Parser
    "clean_json",
    "invoke_json_prompt",
    # Prompts
    "CANDIDATE_EVALUATION_PROMPT",
    "REQUIREMENT_EXTRACTION_PROMPT",
    # Retriever
    "retrieve_candidate",
    # Evaluator (lazy)
    "evaluate_candidate",
]
