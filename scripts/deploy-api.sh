#!/usr/bin/env bash
# ==============================================================
# deploy-api.sh — Deploy ai-recruiter-api with Roles Anywhere
#
# This is the ONLY supported way to deploy the API container.
# It ensures BEDROCK_AWS_PROFILE and all mounts are always present.
#
# Usage:
#   ./scripts/deploy-api.sh
#   ./scripts/deploy-api.sh --dry-run
# ==============================================================

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-2}"
ECR_ACCOUNT="765761474007"
ECR_REPO="ai-recruiter-api"
ECR_TAG="${ECR_TAG:-latest}"
CONTAINER_NAME="ai-recruiter-api"
NETWORK_NAME="ai-recruiter"

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

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_ok()    { echo -e "${GREEN}✓${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }
log_warn()  { echo -e "${YELLOW}⚠${NC} $1"; }

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

# ============================================================
# PREFLIGHT CHECKS
# ============================================================

echo "━━━ Preflight Checks ━━━"

MISSING=0

for f in "$HOST_AWS_CONFIG" "$HOST_SIGNING_HELPER" "$HOST_CLIENT_CRT" "$HOST_CLIENT_KEY"; do
    if [[ ! -f "$f" ]]; then
        log_error "Missing required file: $f"
        MISSING=1
    else
        log_ok "Found: $f"
    fi
done

# Verify AWS config uses container paths (not host paths)
if grep -q "/opt/ai-recruiter" "$HOST_AWS_CONFIG" 2>/dev/null; then
    log_error "AWS config contains host paths instead of container paths!"
    log_error "Expected: /run/rolesanywhere/client.crt"
    log_error "Found: paths starting with /opt/ai-recruiter"
    MISSING=1
else
    log_ok "AWS config uses container paths"
fi

# Verify AWS config has the profile
if ! grep -q "$BEDROCK_PROFILE" "$HOST_AWS_CONFIG" 2>/dev/null; then
    log_error "AWS config missing profile: $BEDROCK_PROFILE"
    MISSING=1
else
    log_ok "AWS config has profile: $BEDROCK_PROFILE"
fi

if [[ $MISSING -ne 0 ]]; then
    log_error "Preflight checks FAILED. Aborting deploy."
    exit 1
fi

log_ok "All preflight checks passed"

# ============================================================
# PULL IMAGE
# ============================================================

echo ""
echo "━━━ Pull Image ━━━"

ECR_IMAGE="${ECR_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${ECR_TAG}"

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] docker pull $ECR_IMAGE"
else
    # Try to pull; if it fails (e.g. no ECR permissions), use local image
    if docker pull "$ECR_IMAGE" 2>/dev/null; then
        log_ok "Image pulled: $ECR_IMAGE"
    else
        # Check if image exists locally
        if docker image inspect "$ECR_IMAGE" >/dev/null 2>&1; then
            log_warn "ECR pull failed (no permissions), using local image: $ECR_IMAGE"
        else
            log_error "Image not available locally or in ECR: $ECR_IMAGE"
            exit 1
        fi
    fi
fi

# ============================================================
# STOP OLD CONTAINER
# ============================================================

echo ""
echo "━━━ Stop Old Container ━━━"

if docker ps -q -f "name=$CONTAINER_NAME" | grep -q .; then
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[DRY RUN] docker stop $CONTAINER_NAME"
        echo "[DRY RUN] docker rm $CONTAINER_NAME"
    else
        docker stop "$CONTAINER_NAME" 2>/dev/null || true
        docker rm "$CONTAINER_NAME" 2>/dev/null || true
        log_ok "Old container stopped"
    fi
else
    log_ok "No existing container to stop"
fi

# ============================================================
# CREATE NEW CONTAINER
# ============================================================

echo ""
echo "━━━ Create Container ━━━"

DOCKER_ARGS=(
    -d
    --name "$CONTAINER_NAME"
    --restart unless-stopped
    --network "$NETWORK_NAME"
    --add-host=host.docker.internal:host-gateway
    # Database
    -e "DATABASE_URL=postgresql://postgres:postgres@host.docker.internal:5432/ai_recruiter"
    # AWS
    -e "AWS_REGION=$AWS_REGION"
    -e "BEDROCK_AWS_PROFILE=$BEDROCK_PROFILE"
    # Cognito
    -e "COGNITO_USER_POOL_ID=us-east-2_AkQ5UIW7R"
    -e "COGNITO_CLIENT_ID=73ts1mbn3qla00uc15di6ihvju"
    # Roles Anywhere mounts (read-only)
    -v "${HOST_AWS_CONFIG}:${CONTAINER_AWS_CONFIG}:ro"
    -v "${HOST_SIGNING_HELPER}:${CONTAINER_SIGNING_HELPER}:ro"
    -v "${HOST_CLIENT_CRT}:${CONTAINER_CLIENT_CRT}:ro"
    -v "${HOST_CLIENT_KEY}:${CONTAINER_CLIENT_KEY}:ro"
    # Image
    "$ECR_IMAGE"
)

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] docker run ${DOCKER_ARGS[*]}"
else
    docker run "${DOCKER_ARGS[@]}"
    log_ok "Container created: $CONTAINER_NAME"
fi

# ============================================================
# WAIT FOR STARTUP
# ============================================================

echo ""
echo "━━━ Wait for Startup ━━━"

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] sleep 15"
else
    sleep 15
fi

# ============================================================
# POST-DEPLOY CHECKS
# ============================================================

echo ""
echo "━━━ Post-Deploy Checks ━━━"

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] Skipping post-deploy checks"
    exit 0
fi

# Check 1: BEDROCK_AWS_PROFILE in container
CONTAINER_ENV=$(docker inspect "$CONTAINER_NAME" --format '{{range .Config.Env}}{{println .}}{{end}}')
if echo "$CONTAINER_ENV" | grep -q "BEDROCK_AWS_PROFILE=ai-recruiter-bedrock"; then
    log_ok "BEDROCK_AWS_PROFILE=ai-recruiter-bedrock"
else
    log_error "BEDROCK_AWS_PROFILE not set!"
    exit 1
fi

# Check 2: Mounts present
MOUNTS=$(docker inspect "$CONTAINER_NAME" --format '{{range .Mounts}}{{.Source}} {{end}}')
MOUNT_COUNT=$(echo "$MOUNTS" | wc -w)
if [[ $MOUNT_COUNT -ge 4 ]]; then
    log_ok "All 4 mounts present"
else
    log_error "Expected 4 mounts, found $MOUNT_COUNT"
    exit 1
fi

# Check 3: Health check
HEALTH=$(curl -sf http://localhost/api/health 2>/dev/null || echo "FAIL")
if echo "$HEALTH" | grep -q '"status":"ok"'; then
    log_ok "Health check passed"
else
    log_warn "Health check returned: $HEALTH"
fi

# Check 4: AWS caller identity
CALLER=$(docker exec "$CONTAINER_NAME" python -c "
from app import evaluation
s = evaluation._bedrock_session
r = s.client('sts', region_name='us-east-2').get_caller_identity()
print(f\"{r['Account']}|{r['Arn']}\")
" 2>/dev/null || echo "FAIL")

if echo "$CALLER" | grep -q "765761474007"; then
    log_ok "AWS Account: 765761474007"
else
    log_error "AWS caller identity wrong: $CALLER"
    exit 1
fi

if echo "$CALLER" | grep -q "AiRecruiterBedrockRuntimeRole"; then
    log_ok "AWS Role: AiRecruiterBedrockRuntimeRole"
else
    log_error "AWS role wrong: $CALLER"
    exit 1
fi

echo ""
log_ok "Deploy completed successfully!"
echo "  Container: $CONTAINER_NAME"
echo "  Image: $ECR_IMAGE"
echo "  Profile: $BEDROCK_PROFILE"
