#!/usr/bin/env bash
# ==============================================================
# deploy-worker.sh — Deploy ai-recruiter-worker with Roles Anywhere
#
# Runs the durable candidate import SQS worker from the exact same
# immutable backend image used by the API.
# ==============================================================

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-2}"
ECR_ACCOUNT="765761474007"
ECR_REPO="ai-recruiter-api"
ECR_TAG="${ECR_TAG:-latest}"
CONTAINER_NAME="ai-recruiter-worker"
NETWORK_NAME="ai-recruiter"
DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@host.docker.internal:5432/ai_recruiter}"
IMPORT_STAGING_BUCKET="${IMPORT_STAGING_BUCKET:?IMPORT_STAGING_BUCKET is required}"
IMPORT_QUEUE_URL="${IMPORT_QUEUE_URL:?IMPORT_QUEUE_URL is required}"
IMPORT_EVALUATION_CONCURRENCY="${IMPORT_EVALUATION_CONCURRENCY:-3}"

# Roles Anywhere paths (HOST)
HOST_AWS_CONFIG="/opt/ai-recruiter/aws/config"
HOST_SIGNING_HELPER="/usr/local/bin/aws_signing_helper"
HOST_CLIENT_CRT="/opt/ai-recruiter/rolesanywhere/client.crt"
HOST_CLIENT_KEY="/opt/ai-recruiter/rolesanywhere/client.key"

# Roles Anywhere paths (CONTAINER)
CONTAINER_AWS_CONFIG="/root/.aws/config"
CONTAINER_SIGNING_HELPER="/usr/local/bin/aws_signing_helper"
CONTAINER_CLIENT_CRT="/run/rolesanywhere/client.crt"
CONTAINER_CLIENT_KEY="/run/rolesanywhere/client.key"

BEDROCK_PROFILE="ai-recruiter-bedrock"
ECR_IMAGE="${ECR_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${ECR_TAG}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_ok()    { echo -e "${GREEN}✓${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }
log_warn()  { echo -e "${YELLOW}⚠${NC} $1"; }

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

rollback_worker() {
    local old_image="${1:-}"
    if [[ -z "$old_image" ]]; then
        return 0
    fi

    log_warn "Attempting worker rollback to $old_image"
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
        -e "IMPORT_EVALUATION_CONCURRENCY=$IMPORT_EVALUATION_CONCURRENCY" \
        -v "${HOST_AWS_CONFIG}:${CONTAINER_AWS_CONFIG}:ro" \
        -v "${HOST_SIGNING_HELPER}:${CONTAINER_SIGNING_HELPER}:ro" \
        -v "${HOST_CLIENT_CRT}:${CONTAINER_CLIENT_CRT}:ro" \
        -v "${HOST_CLIENT_KEY}:${CONTAINER_CLIENT_KEY}:ro" \
        "$old_image" python -m app.workers.candidate_imports >/dev/null
    log_warn "Worker rollback attempted"
}

# ============================================================
# PREFLIGHT
# ============================================================

echo "━━━ Worker Preflight Checks ━━━"
MISSING=0
for f in "$HOST_AWS_CONFIG" "$HOST_SIGNING_HELPER" "$HOST_CLIENT_CRT" "$HOST_CLIENT_KEY"; do
    if [[ ! -f "$f" ]]; then
        log_error "Missing required file: $f"
        MISSING=1
    else
        log_ok "Found: $f"
    fi
done

if grep -q "/opt/ai-recruiter" "$HOST_AWS_CONFIG" 2>/dev/null; then
    log_error "AWS config contains host paths instead of container paths"
    MISSING=1
fi

if ! grep -q "$BEDROCK_PROFILE" "$HOST_AWS_CONFIG" 2>/dev/null; then
    log_error "AWS config missing profile: $BEDROCK_PROFILE"
    MISSING=1
fi

if [[ $MISSING -ne 0 ]]; then
    log_error "Worker preflight failed"
    exit 1
fi

# ============================================================
# IMAGE + ROLLBACK SNAPSHOT
# ============================================================

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] docker pull $ECR_IMAGE"
else
    if docker pull "$ECR_IMAGE" 2>/dev/null; then
        log_ok "Image pulled: $ECR_IMAGE"
    elif docker image inspect "$ECR_IMAGE" >/dev/null 2>&1; then
        log_warn "ECR pull failed; using local immutable image"
    else
        log_error "Image not available: $ECR_IMAGE"
        exit 1
    fi
fi

OLD_WORKER_IMAGE=""
if docker inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    OLD_WORKER_IMAGE=$(docker inspect "$CONTAINER_NAME" --format '{{.Config.Image}}')
    log_ok "Preserved worker rollback image: $OLD_WORKER_IMAGE"
fi

# ============================================================
# REPLACE WORKER
# ============================================================

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] docker rm -f $CONTAINER_NAME"
    echo "[DRY RUN] docker run ... $ECR_IMAGE python -m app.workers.candidate_imports"
    exit 0
fi

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

if ! docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    --network "$NETWORK_NAME" \
    --add-host=host.docker.internal:host-gateway \
    -e "DATABASE_URL=$DATABASE_URL" \
    -e "AWS_REGION=$AWS_REGION" \
    -e "BEDROCK_AWS_PROFILE=$BEDROCK_PROFILE" \
    -e "IMPORT_STAGING_BUCKET=$IMPORT_STAGING_BUCKET" \
    -e "IMPORT_QUEUE_URL=$IMPORT_QUEUE_URL" \
    -e "IMPORT_EVALUATION_CONCURRENCY=$IMPORT_EVALUATION_CONCURRENCY" \
    -v "${HOST_AWS_CONFIG}:${CONTAINER_AWS_CONFIG}:ro" \
    -v "${HOST_SIGNING_HELPER}:${CONTAINER_SIGNING_HELPER}:ro" \
    -v "${HOST_CLIENT_CRT}:${CONTAINER_CLIENT_CRT}:ro" \
    -v "${HOST_CLIENT_KEY}:${CONTAINER_CLIENT_KEY}:ro" \
    "$ECR_IMAGE" python -m app.workers.candidate_imports; then
    rollback_worker "$OLD_WORKER_IMAGE"
    exit 1
fi

sleep 5

# ============================================================
# POST-DEPLOY CHECKS
# ============================================================

STATUS=$(docker inspect "$CONTAINER_NAME" --format '{{.State.Status}}' 2>/dev/null || echo "MISSING")
if [[ "$STATUS" != "running" ]]; then
    log_error "Worker is not running: $STATUS"
    docker logs --tail 100 "$CONTAINER_NAME" 2>&1 || true
    rollback_worker "$OLD_WORKER_IMAGE"
    exit 1
fi
log_ok "Worker container running"

WORKER_IMAGE=$(docker inspect "$CONTAINER_NAME" --format '{{.Config.Image}}')
if [[ "$WORKER_IMAGE" != "$ECR_IMAGE" ]]; then
    log_error "Worker image mismatch: $WORKER_IMAGE"
    rollback_worker "$OLD_WORKER_IMAGE"
    exit 1
fi
log_ok "Worker image is immutable tag: $ECR_TAG"

CONTAINER_ENV=$(docker inspect "$CONTAINER_NAME" --format '{{range .Config.Env}}{{println .}}{{end}}')
for required in \
    "BEDROCK_AWS_PROFILE=$BEDROCK_PROFILE" \
    "IMPORT_STAGING_BUCKET=$IMPORT_STAGING_BUCKET" \
    "IMPORT_QUEUE_URL=$IMPORT_QUEUE_URL" \
    "IMPORT_EVALUATION_CONCURRENCY=$IMPORT_EVALUATION_CONCURRENCY"; do
    if ! echo "$CONTAINER_ENV" | grep -Fqx "$required"; then
        log_error "Worker missing runtime environment: ${required%%=*}"
        rollback_worker "$OLD_WORKER_IMAGE"
        exit 1
    fi
done

MOUNTS=$(docker inspect "$CONTAINER_NAME" --format '{{range .Mounts}}{{.Destination}} {{end}}')
for dest in "$CONTAINER_AWS_CONFIG" "$CONTAINER_SIGNING_HELPER" "$CONTAINER_CLIENT_CRT" "$CONTAINER_CLIENT_KEY"; do
    if ! echo "$MOUNTS" | grep -q "$dest"; then
        log_error "Worker mount missing: $dest"
        rollback_worker "$OLD_WORKER_IMAGE"
        exit 1
    fi
done

CALLER=$(docker exec "$CONTAINER_NAME" python -c "
from app.infrastructure.bedrock.session import get_cached_session
r = get_cached_session().client('sts', region_name='us-east-2').get_caller_identity()
print(f\"{r['Account']}|{r['Arn']}\")
" 2>/dev/null || echo "FAIL")

if ! echo "$CALLER" | grep -q "765761474007"; then
    log_error "Worker AWS account check failed: $CALLER"
    rollback_worker "$OLD_WORKER_IMAGE"
    exit 1
fi
if ! echo "$CALLER" | grep -q "AiRecruiterBedrockRuntimeRole"; then
    log_error "Worker AWS role check failed: $CALLER"
    rollback_worker "$OLD_WORKER_IMAGE"
    exit 1
fi

log_ok "Worker AWS runtime identity verified"
log_ok "Worker deploy completed successfully"
echo "  Container: $CONTAINER_NAME"
echo "  Image: $ECR_IMAGE"
echo "  Command: python -m app.workers.candidate_imports"
