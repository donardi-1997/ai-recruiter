#!/usr/bin/env bash
# Deploy the API container using the immutable ECR image and Roles Anywhere.
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-2}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:?AWS_ACCOUNT_ID is required}"
EXPECTED_AWS_ACCOUNT="${EXPECTED_AWS_ACCOUNT:-$AWS_ACCOUNT_ID}"
ECR_REPO="ai-recruiter-api"
ECR_TAG="${ECR_TAG:-latest}"
CONTAINER_NAME="ai-recruiter-api"
NETWORK_NAME="ai-recruiter"
DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@host.docker.internal:5432/ai_recruiter}"
IMPORT_STAGING_BUCKET="${IMPORT_STAGING_BUCKET:?IMPORT_STAGING_BUCKET is required}"
IMPORT_QUEUE_URL="${IMPORT_QUEUE_URL:?IMPORT_QUEUE_URL is required}"
TRAINING_CONTENT_BUCKET="${TRAINING_CONTENT_BUCKET:?TRAINING_CONTENT_BUCKET is required}"
IMPORT_EVALUATION_CONCURRENCY="${IMPORT_EVALUATION_CONCURRENCY:-1}"
PG_POOL_SIZE="${PG_POOL_SIZE:-2}"
PG_MAX_OVERFLOW="${PG_MAX_OVERFLOW:-2}"
S3_BUCKET="${S3_BUCKET:?S3_BUCKET is required}"
KNOWLEDGE_BASE_ID="${KNOWLEDGE_BASE_ID:?KNOWLEDGE_BASE_ID is required}"
DATA_SOURCE_ID="${DATA_SOURCE_ID:?DATA_SOURCE_ID is required}"
COGNITO_USER_POOL_ID="${COGNITO_USER_POOL_ID:?COGNITO_USER_POOL_ID is required}"
COGNITO_CLIENT_ID="${COGNITO_CLIENT_ID:?COGNITO_CLIENT_ID is required}"
ALLOW_PUBLIC_REGISTRATION="${ALLOW_PUBLIC_REGISTRATION:-false}"
RBAC_BOOTSTRAP_ADMIN_EMAILS="${RBAC_BOOTSTRAP_ADMIN_EMAILS:-}"
RBAC_BOOTSTRAP_SUPER_ADMIN_EMAILS="${RBAC_BOOTSTRAP_SUPER_ADMIN_EMAILS:-}"

HOST_AWS_CONFIG="/opt/ai-recruiter/aws/config"
HOST_SIGNING_HELPER="/usr/local/bin/aws_signing_helper"
HOST_CLIENT_CRT="/opt/ai-recruiter/rolesanywhere/client.crt"
HOST_CLIENT_KEY="/opt/ai-recruiter/rolesanywhere/client.key"
CONTAINER_AWS_CONFIG="/root/.aws/config"
CONTAINER_SIGNING_HELPER="/usr/local/bin/aws_signing_helper"
CONTAINER_CLIENT_CRT="/run/rolesanywhere/client.crt"
CONTAINER_CLIENT_KEY="/run/rolesanywhere/client.key"
BEDROCK_PROFILE="ai-recruiter-bedrock"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
ECR_IMAGE="${ECR_REGISTRY}/${ECR_REPO}:${ECR_TAG}"

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

for file in "$HOST_AWS_CONFIG" "$HOST_SIGNING_HELPER" "$HOST_CLIENT_CRT" "$HOST_CLIENT_KEY"; do
  [[ -f "$file" ]] || { echo "Missing required file: $file" >&2; exit 1; }
done
grep -q "$BEDROCK_PROFILE" "$HOST_AWS_CONFIG" || { echo "Missing profile $BEDROCK_PROFILE" >&2; exit 1; }

if [[ "$DRY_RUN" == "true" ]]; then
  echo "[DRY RUN] aws ecr get-login-password --region $AWS_REGION --profile $BEDROCK_PROFILE | docker login $ECR_REGISTRY"
  echo "[DRY RUN] docker pull $ECR_IMAGE"
  echo "[DRY RUN] docker run ai-recruiter-api"
  exit 0
fi

AWS_CONFIG_FILE="$HOST_AWS_CONFIG" aws ecr get-login-password --region "$AWS_REGION" --profile "$BEDROCK_PROFILE" | \
  docker login --username AWS --password-stdin "$ECR_REGISTRY"
docker pull "$ECR_IMAGE"
docker network inspect "$NETWORK_NAME" >/dev/null 2>&1 || docker network create "$NETWORK_NAME"
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  --network "$NETWORK_NAME" \
  --add-host=host.docker.internal:host-gateway \
  -e "DATABASE_URL=$DATABASE_URL" \
  -e "AWS_REGION=$AWS_REGION" \
  -e "BEDROCK_AWS_PROFILE=$BEDROCK_PROFILE" \
  -e "IMPORT_STAGING_BUCKET=$IMPORT_STAGING_BUCKET" \
  -e "IMPORT_QUEUE_URL=$IMPORT_QUEUE_URL" \
  -e "TRAINING_CONTENT_BUCKET=$TRAINING_CONTENT_BUCKET" \
  -e "IMPORT_EVALUATION_CONCURRENCY=$IMPORT_EVALUATION_CONCURRENCY" \
  -e "PG_POOL_SIZE=$PG_POOL_SIZE" \
  -e "PG_MAX_OVERFLOW=$PG_MAX_OVERFLOW" \
  -e "S3_BUCKET=$S3_BUCKET" \
  -e "KNOWLEDGE_BASE_ID=$KNOWLEDGE_BASE_ID" \
  -e "DATA_SOURCE_ID=$DATA_SOURCE_ID" \
  -e "COGNITO_USER_POOL_ID=$COGNITO_USER_POOL_ID" \
  -e "COGNITO_CLIENT_ID=$COGNITO_CLIENT_ID" \
  -e "ALLOW_PUBLIC_REGISTRATION=$ALLOW_PUBLIC_REGISTRATION" \
  -e "RBAC_BOOTSTRAP_ADMIN_EMAILS=$RBAC_BOOTSTRAP_ADMIN_EMAILS" \
  -e "RBAC_BOOTSTRAP_SUPER_ADMIN_EMAILS=$RBAC_BOOTSTRAP_SUPER_ADMIN_EMAILS" \
  -v "${HOST_AWS_CONFIG}:${CONTAINER_AWS_CONFIG}:ro" \
  -v "${HOST_SIGNING_HELPER}:${CONTAINER_SIGNING_HELPER}:ro" \
  -v "${HOST_CLIENT_CRT}:${CONTAINER_CLIENT_CRT}:ro" \
  -v "${HOST_CLIENT_KEY}:${CONTAINER_CLIENT_KEY}:ro" \
  "$ECR_IMAGE"

sleep 5
[[ "$(docker inspect "$CONTAINER_NAME" --format '{{.State.Status}}')" == "running" ]]

CONTAINER_ENV=$(docker inspect "$CONTAINER_NAME" --format '{{range .Config.Env}}{{println .}}{{end}}')
for required in \
  "BEDROCK_AWS_PROFILE=$BEDROCK_PROFILE" \
  "IMPORT_STAGING_BUCKET=$IMPORT_STAGING_BUCKET" \
  "IMPORT_QUEUE_URL=$IMPORT_QUEUE_URL" \
  "TRAINING_CONTENT_BUCKET=$TRAINING_CONTENT_BUCKET" \
  "IMPORT_EVALUATION_CONCURRENCY=$IMPORT_EVALUATION_CONCURRENCY" \
  "PG_POOL_SIZE=$PG_POOL_SIZE" \
  "PG_MAX_OVERFLOW=$PG_MAX_OVERFLOW" \
  "S3_BUCKET=$S3_BUCKET" \
  "KNOWLEDGE_BASE_ID=$KNOWLEDGE_BASE_ID" \
  "DATA_SOURCE_ID=$DATA_SOURCE_ID" \
  "COGNITO_USER_POOL_ID=$COGNITO_USER_POOL_ID" \
  "COGNITO_CLIENT_ID=$COGNITO_CLIENT_ID" \
  "ALLOW_PUBLIC_REGISTRATION=$ALLOW_PUBLIC_REGISTRATION" \
  "RBAC_BOOTSTRAP_ADMIN_EMAILS=$RBAC_BOOTSTRAP_ADMIN_EMAILS" \
  "RBAC_BOOTSTRAP_SUPER_ADMIN_EMAILS=$RBAC_BOOTSTRAP_SUPER_ADMIN_EMAILS"; do
  echo "$CONTAINER_ENV" | grep -Fqx "$required" || { echo "Missing runtime env ${required%%=*}" >&2; exit 1; }
done

CALLER=$(docker exec "$CONTAINER_NAME" python -c "from app.infrastructure.bedrock.session import get_cached_session; r=get_cached_session().client('sts', region_name='us-east-2').get_caller_identity(); print(f\"{r['Account']}|{r['Arn']}\")")
echo "$CALLER" | grep -q "$EXPECTED_AWS_ACCOUNT" || { echo "AWS account mismatch: $CALLER" >&2; exit 1; }
echo "$CALLER" | grep -q "AiRecruiterBedrockRuntimeRole" || { echo "AWS role mismatch: $CALLER" >&2; exit 1; }

echo "DEPLOY_API_OK"
