"""Bedrock infrastructure configuration.

Centralized configuration constants for AWS Bedrock integration.
"""

import os

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

AWS_REGION = os.getenv("AWS_REGION", "us-east-2")
KNOWLEDGE_BASE_ID = os.getenv("KNOWLEDGE_BASE_ID", "VUGNMJQAEN")
BEDROCK_AWS_PROFILE = os.getenv("BEDROCK_AWS_PROFILE")
NUMBER_OF_RESULTS = 50
MODEL_ID = "amazon.nova-lite-v1:0"
MODEL_TEMPERATURE = 0

# ============================================================
# DERIVED SETTINGS
# ============================================================

# Model kwargs for ChatBedrock
MODEL_KWARGS = {"temperature": MODEL_TEMPERATURE}

# Retrieval configuration
RETRIEVAL_CONFIG = {
    "vectorSearchConfiguration": {
        "numberOfResults": NUMBER_OF_RESULTS,
    }
}