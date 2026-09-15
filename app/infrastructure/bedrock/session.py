"""AWS Bedrock session management.

Provides the canonical Bedrock session using IAM Roles Anywhere
profile or default credential chain.
"""

import logging
import os

import boto3

from app.infrastructure.bedrock.config import BEDROCK_AWS_PROFILE

logger = logging.getLogger(__name__)


def get_bedrock_session() -> boto3.Session:
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


# Process-level singleton session (mirrors original module-level behavior)
_bedrock_session = get_bedrock_session()


def get_cached_session() -> boto3.Session:
    """Return the cached process-level Bedrock session."""
    return _bedrock_session