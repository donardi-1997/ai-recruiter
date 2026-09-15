"""Bedrock service clients.

Provides canonical Bedrock service clients using the canonical session.
"""

import logging

from app.infrastructure.bedrock.config import (
    AWS_REGION,
    MODEL_ID,
    MODEL_KWARGS,
)
from app.infrastructure.bedrock.session import get_cached_session
from langchain_aws import ChatBedrock

logger = logging.getLogger(__name__)

_session = get_cached_session()

# Bedrock Agent Runtime client for Knowledge Base retrieval
bedrock_agent_runtime = _session.client(
    "bedrock-agent-runtime",
    region_name=AWS_REGION,
)

# Bedrock Runtime client for LLM invocation
bedrock_runtime = _session.client(
    "bedrock-runtime",
    region_name=AWS_REGION,
)

# LangChain ChatBedrock instance for LLM evaluation
llm = ChatBedrock(
    client=bedrock_runtime,
    model_id="amazon.nova-lite-v1:0",
    region_name=AWS_REGION,
    model_kwargs={"temperature": 0},
)


def get_bedrock_agent_runtime():
    """Return the cached bedrock-agent-runtime client."""
    return bedrock_agent_runtime


def get_bedrock_runtime():
    """Return the cached bedrock-runtime client."""
    return bedrock_runtime


def get_llm() -> ChatBedrock:
    """Return the cached LangChain ChatBedrock instance."""
    return llm