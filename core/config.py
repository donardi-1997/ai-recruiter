import logging
import os

from dotenv import load_dotenv

load_dotenv()

# ============================================================
# LOGGING
# ============================================================

logger = logging.getLogger(__name__)

if not logging.getLogger().handlers:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

# ============================================================
# AWS CONFIGURATION
# ============================================================

AWS_REGION = os.getenv("AWS_REGION", "us-east-2")
AWS_ENDPOINT = os.getenv("AWS_ENDPOINT", "")
KNOWLEDGE_BASE_ID = os.getenv("KNOWLEDGE_BASE_ID", "VUGNMJQAEN")
DATA_SOURCE_ID = os.getenv("DATA_SOURCE_ID", "P8SUL2VFHA")
S3_BUCKET = "ai-cv-rag-adrian-2026"
S3_PREFIX = "documents"
NUMBER_OF_RESULTS = 50
MAX_CV_SIZE_BYTES = 15 * 1024 * 1024

# ============================================================
# COGNITO CONFIGURATION
# ============================================================

COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID")
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID")
COGNITO_ISSUER = (
    f"https://cognito-idp.{AWS_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}"
)
COGNITO_JWKS_URL = f"{COGNITO_ISSUER}/.well-known/jwks.json"

# ============================================================
# DYNAMODB TABLE NAMES
# ============================================================

CANDIDATES_TABLE = "ai-recruiter-candidates"
JOBS_TABLE = "ai-recruiter-jobs"
EVALUATIONS_TABLE = "ai-recruiter-evaluations"
JOB_CANDIDATES_TABLE = os.getenv(
    "JOB_CANDIDATES_TABLE", "ai-recruiter-job-candidates"
)
RANKINGS_TABLE = "ai-recruiter-rankings"

# ============================================================
# CORS ORIGINS
# ============================================================

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:5175",
    "https://ai.adrianguerra.net",
    "https://d2c1mv108wl5wv.cloudfront.net",
]
