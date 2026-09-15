"""Knowledge Base retrieval for candidate CVs.

Provides the canonical retrieval function using Bedrock Agent Runtime.
"""

import logging

from app.infrastructure.bedrock.clients import get_bedrock_agent_runtime
from app.infrastructure.bedrock.config import KNOWLEDGE_BASE_ID, RETRIEVAL_CONFIG

logger = logging.getLogger(__name__)


def retrieve_candidate(candidate_id: str, question: str) -> list:
    """Retrieve CV context from Bedrock Knowledge Base for a candidate.

    Args:
        candidate_id: Canonical candidate UUID
        question: Job description or title to query against

    Returns:
        List of retrieval results from Bedrock Knowledge Base
    """
    client = get_bedrock_agent_runtime()
    response = client.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={"text": question},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": 50,
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