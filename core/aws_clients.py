import boto3
import botocore.exceptions

from core.config import (
    AWS_REGION,
    AWS_ENDPOINT,
    CANDIDATES_TABLE,
    JOBS_TABLE,
    EVALUATIONS_TABLE,
    JOB_CANDIDATES_TABLE,
    RANKINGS_TABLE,
    logger,
)

# ============================================================
# AWS CLIENTS
# ============================================================

s3 = boto3.client("s3", region_name=AWS_REGION)
bedrock_agent = boto3.client("bedrock-agent", region_name=AWS_REGION)
bedrock_agent_runtime = boto3.client(
    "bedrock-agent-runtime", region_name=AWS_REGION
)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)

# ============================================================
# DYNAMODB TABLES
# ============================================================

candidates_table = dynamodb.Table(CANDIDATES_TABLE)
jobs_table = dynamodb.Table(JOBS_TABLE)
evaluations_table = dynamodb.Table(EVALUATIONS_TABLE)
job_candidates_table = dynamodb.Table(JOB_CANDIDATES_TABLE)
rankings_table = dynamodb.Table(RANKINGS_TABLE)


# ============================================================
# RANKINGS TABLE HELPERS
# ============================================================


def get_rankings_dynamodb_client():
    client_kwargs = {"region_name": AWS_REGION}
    if AWS_ENDPOINT:
        client_kwargs["endpoint_url"] = AWS_ENDPOINT
    return boto3.client("dynamodb", **client_kwargs)


def get_rankings_dynamodb_resource():
    resource_kwargs = {"region_name": AWS_REGION}
    if AWS_ENDPOINT:
        resource_kwargs["endpoint_url"] = AWS_ENDPOINT
    return boto3.resource("dynamodb", **resource_kwargs)


def ensure_rankings_table_exists() -> bool:
    client = get_rankings_dynamodb_client()
    try:
        client.describe_table(TableName=RANKINGS_TABLE)
        logger.info("Rankings table already exists: %s", RANKINGS_TABLE)
        return True
    except botocore.exceptions.ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")
        if error_code != "ResourceNotFoundException":
            logger.exception(
                "Error verifying rankings table '%s': %s",
                RANKINGS_TABLE,
                error,
            )
            return False

    try:
        logger.info("Creating rankings table: %s", RANKINGS_TABLE)
        client.create_table(
            TableName=RANKINGS_TABLE,
            KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "job_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        waiter = client.get_waiter("table_exists")
        waiter.wait(TableName=RANKINGS_TABLE)
        logger.info("Rankings table created: %s", RANKINGS_TABLE)
        return True
    except botocore.exceptions.ClientError as error:
        logger.exception(
            "Error creating rankings table '%s': %s",
            RANKINGS_TABLE,
            error,
        )
        return False
