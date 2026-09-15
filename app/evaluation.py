"""Compatibility facade for app.evaluation.

This module maintains backward compatibility for existing imports.
All canonical implementations have been moved to app.infrastructure.bedrock.
"""

import logging

from app.infrastructure.bedrock.config import (
    AWS_REGION,
    BEDROCK_AWS_PROFILE,
    KNOWLEDGE_BASE_ID,
    NUMBER_OF_RESULTS,
)
from app.infrastructure.bedrock.session import get_bedrock_session, get_cached_session
from app.infrastructure.bedrock.clients import (
    bedrock_agent_runtime,
    bedrock_runtime,
    llm,
)
from app.infrastructure.bedrock.parser import clean_json, invoke_json_prompt
from app.infrastructure.bedrock.retriever import retrieve_candidate
from app.infrastructure.bedrock.evaluator import evaluate_candidate
from app.domains.evaluations.rules import recommendation_for_score

logger = logging.getLogger(__name__)

# ============================================================
# BACKWARD COMPATIBILITY EXPORTS
# ============================================================

# Configuration constants (module-level for backward compatibility)
AWS_REGION = AWS_REGION
KNOWLEDGE_BASE_ID = KNOWLEDGE_BASE_ID
BEDROCK_AWS_PROFILE = BEDROCK_AWS_PROFILE
NUMBER_OF_RESULTS = NUMBER_OF_RESULTS

# Session (process-level singleton)
_bedrock_session = get_cached_session()

# Bedrock clients (module-level for backward compatibility)
bedrock_agent_runtime = bedrock_agent_runtime
bedrock_runtime = bedrock_runtime

# LangChain LLM
llm = llm

# Functions
clean_json = clean_json
invoke_json_prompt = invoke_json_prompt
retrieve_candidate = retrieve_candidate
evaluate_candidate = evaluate_candidate
recommendation_for_score = recommendation_for_score

# For explicit import control
__all__ = [
    # Configuration
    "AWS_REGION",
    "KNOWLEDGE_BASE_ID",
    "BEDROCK_AWS_PROFILE",
    "NUMBER_OF_RESULTS",
    # Session
    "_bedrock_session",
    "get_bedrock_session",
    # Clients
    "bedrock_agent_runtime",
    "bedrock_runtime",
    # LLM
    "llm",
    # Parser
    "clean_json",
    "invoke_json_prompt",
    # Retriever
    "retrieve_candidate",
    # Evaluator
    "evaluate_candidate",
    # Rules
    "recommendation_for_score",
]

# Import get_cached_session to make it available via app.evaluation
from app.infrastructure.bedrock.session import get_cached_session