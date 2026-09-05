#!/usr/bin/env bash
# ==============================================================
# deploy-lightsail.sh — Desplegar AI Recruiter en Lightsail
#
# Uso:
#   ./scripts/deploy-lightsail.sh              # Deploy completo
#   ./scripts/deploy-lightsail.sh --dry-run    # Solo mostrar comandos
#   ./scripts/deploy-lightsail.sh --status     # Verificar estado
#   ./scripts/deploy-lightsail.sh --endpoint   # Mostrar URL pública
#
# Variables requeridas (exportar antes de ejecutar):
#   REEMPLAZAR_AWS_REGION
#   REEMPLAZAR_SERVICE_NAME
#   REEMPLAZAR_IMAGE
#   REEMPLAZAR_IMAGE_LABEL
# ==============================================================

set -euo pipefail

# ============================================================
# CONFIGURACIÓN
# ============================================================

AWS_REGION="${REEMPLAZAR_AWS_REGION:-us-east-2}"
SERVICE_NAME="${REEMPLAZAR_SERVICE_NAME:-ai-recruiter}"
IMAGE_NAME="${REEMPLAZAR_IMAGE:-ai-recruiter-api}"
IMAGE_LABEL="${REEMPLAZAR_IMAGE_LABEL:-latest}"
CONTAINER_NAME="app"
CONTAINER_PORT=80
HEALTH_CHECK_PATH="/health"
HEALTH_CHECK_SUCCESS="200"
SCALE=1
POWER="small"
PUBLIC_ENDPOINT=true

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}ℹ${NC}  $1"; }
log_ok()    { echo -e "${GREEN}✓${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}⚠${NC}  $1"; }
log_error() { echo -e "${RED}✗${NC}  $1"; }
log_step()  { echo -e "\n${BLUE}━━━ $1 ━━━${NC}"; }

DRY_RUN=false
ACTION="deploy"

# Parse args
for arg in "$@"; do
  case $arg in
    --dry-run) DRY_RUN=true ;;
    --status)  ACTION="status" ;;
    --endpoint) ACTION="endpoint" ;;
    --help|-h)
      echo "Uso: $0 [--dry-run|--status|--endpoint]"
      exit 0
      ;;
  esac
done

# ============================================================
# VALIDACIONES
# ============================================================

validate_env() {
  local missing=()

  [ -z "$AWS_REGION" ]       && missing+=("REEMPLAZAR_AWS_REGION")
  [ -z "$SERVICE_NAME" ]     && missing+=("REEMPLAZAR_SERVICE_NAME")
  [ -z "$IMAGE_NAME" ]       && missing+=("REEMPLAZAR_IMAGE")
  [ -z "$IMAGE_LABEL" ]      && missing+=("REEMPLAZAR_IMAGE_LABEL")

  if [ ${#missing[@]} -gt 0 ]; then
    log_error "Variables faltantes:"
    for v in "${missing[@]}"; do
      echo "  export $v=REEMPLAZAR_AQUI"
    done
    exit 1
  fi

  # Verificar AWS CLI
  if ! command -v aws &>/dev/null; then
    log_error "AWS CLI no encontrado. Instalar: pip install awscli"
    exit 1
  fi

  # Verificar Docker
  if ! command -v docker &>/dev/null; then
    log_error "Docker no encontrado. Instalar: https://docs.docker.com/get-docker/"
    exit 1
  fi

  # Verificar credenciales AWS
  if ! aws sts get-caller-identity --region "$AWS_REGION" &>/dev/null; then
    log_error "Credenciales AWS no válidas para región $AWS_REGION"
    exit 1
  fi

  log_ok "Variables de entorno validadas"
}

# ============================================================
# PASO 1: CREAR SERVICE EN LIGHTSAIL
# ============================================================

create_service() {
  log_step "Paso 1: Crear Lightsail Container Service"

  # Verificar si ya existe
  if aws lightsail get-container-services \
    --service-name "$SERVICE_NAME" \
    --region "$AWS_REGION" &>/dev/null; then
    log_warn "Service '$SERVICE_NAME' ya existe — reutilizando"
    return 0
  fi

  log_info "Creando service '$SERVICE_NAME' (power=$POWER, scale=$SCALE)..."

  if [ "$DRY_RUN" = true ]; then
    log_info "[DRY RUN] aws lightsail create-container-service \\
      --service-name $SERVICE_NAME \\
      --power $POWER \\
      --scale $SCALE \\
      --region $AWS_REGION"
    return 0
  fi

  aws lightsail create-container-service \
    --service-name "$SERVICE_NAME" \
    --power "$POWER" \
    --scale "$SCALE" \
    --region "$AWS_REGION"

  log_ok "Service '$SERVICE_NAME' creado"
}

# ============================================================
# PASO 2: CONSTRUIR IMAGEN DOCKER
# ============================================================

build_image() {
  log_step "Paso 2: Construir imagen Docker"

  local full_tag="${IMAGE_NAME}:${IMAGE_LABEL}"

  log_info "Construyendo $full_tag ..."

  if [ "$DRY_RUN" = true ]; then
    log_info "[DRY RUN] docker build --tag $full_tag ."
    return 0
  fi

  docker build \
    --tag "$full_tag" \
    --tag "${IMAGE_NAME}:latest" \
    .

  log_ok "Imagen '$full_tag' construida"
}

# ============================================================
# PASO 3: PUSH A LIGHTSAIL REGISTRY
# ============================================================

push_image() {
  log_step "Paso 3: Push a Lightsail Container Registry"

  log_info "Registrando imagen en Lightsail..."

  if [ "$DRY_RUN" = true ]; then
    log_info "[DRY RUN] aws lightsail push-container-image \\
      --service-name $SERVICE_NAME \\
      --label $IMAGE_LABEL \\
      --image ${IMAGE_NAME}:${IMAGE_LABEL} \\
      --region $AWS_REGION"
    return 0
  fi

  aws lightsail push-container-image \
    --service-name "$SERVICE_NAME" \
    --label "$IMAGE_LABEL" \
    --image "${IMAGE_NAME}:${IMAGE_LABEL}" \
    --region "$AWS_REGION"

  log_ok "Imagen push al registry de Lightsail"
}

# ============================================================
# PASO 4: CREAR DEPLOYMENT
# ============================================================

create_deployment() {
  log_step "Paso 4: Crear deployment"

  local image_ref=":${IMAGE_LABEL}"

  log_info "Desplegando contenedor '$CONTAINER_NAME' (port=$CONTAINER_PORT)..."

  if [ "$DRY_RUN" = true ]; then
    log_info "[DRY RUN] aws lightsail create-container-service-deployment \\
      --service-name $SERVICE_NAME \\
      --containers '{...}' \\
      --public-endpoint '{...}'"
    return 0
  fi

  aws lightsail create-container-service-deployment \
    --service-name "$SERVICE_NAME" \
    --containers "{
      \"${CONTAINER_NAME}\": {
        \"image\": \"${image_ref}\",
        \"environment\": {
          \"DATABASE_URL\": \"REEMPLAZAR_AQUI\"
        },
        \"ports\": {
          \"${CONTAINER_PORT}\": \"HTTP\"
        }
      }
    }" \
    --public-endpoint "{
      \"containerName\": \"${CONTAINER_NAME}\",
      \"containerPort\": ${CONTAINER_PORT},
      \"healthCheck\": {
        \"healthyThreshold\": 2,
        \"unhealthyThreshold\": 3,
        \"timeoutSeconds\": 5,
        \"intervalSeconds\": 30,
        \"path\": \"${HEALTH_CHECK_PATH}\",
        \"successCodes\": \"${HEALTH_CHECK_SUCCESS}\"
      }
    }" \
    --region "$AWS_REGION"

  log_ok "Deployment creado — esperando estabilidad..."
}

# ============================================================
# PASO 5: VERIFICAR ESTADO
# ============================================================

check_status() {
  log_step "Paso 5: Verificar estado del service"

  if [ "$DRY_RUN" = true ]; then
    log_info "[DRY RUN] aws lightsail get-container-services --service-name $SERVICE_NAME"
    return 0
  fi

  aws lightsail get-container-services \
    --service-name "$SERVICE_NAME" \
    --region "$AWS_REGION" \
    --query "containerServices[0].{
      Name:serviceName,
      State:state,
      Power:power,
      Scale:scale,
      Url:url,
      createdAt:createdAt
    }" \
    --output table

  # Verificar deployments
  log_info "Deployments recientes:"
  aws lightsail get-container-service-deployments \
    --service-name "$SERVICE_NAME" \
    --region "$AWS_REGION" \
    --query "deployments[0:3].{
      State:state,
      CreatedAt:createdAt,
      Containers:containers[].{Name:containerName,State:state}
    }" \
    --output table
}

# ============================================================
# PASO 6: OBTENER ENDPOINT PÚBLICO
# ============================================================

get_endpoint() {
  log_step "Paso 6: Endpoint público"

  if [ "$DRY_RUN" = true ]; then
    log_info "[DRY RUN] aws lightsail get-container-services ..."
    return 0
  fi

  local url
  url=$(aws lightsail get-container-services \
    --service-name "$SERVICE_NAME" \
    --region "$AWS_REGION" \
    --query "containerServices[0].url" \
    --output text 2>/dev/null)

  if [ -z "$url" ] || [ "$url" = "None" ]; then
    log_error "No se pudo obtener el endpoint"
    return 1
  fi

  log_ok "Endpoint: $url"
  echo ""
  echo "  Health:  $url${HEALTH_CHECK_PATH}"
  echo "  API:     $url/api/health"
  echo "  Docs:    $url/docs"
  echo ""

  # Test rápido
  log_info "Verificando health check..."
  local http_code
  http_code=$(curl -sf -o /dev/null -w "%{http_code}" "$url${HEALTH_CHECK_PATH}" 2>/dev/null || echo "000")

  if [ "$http_code" = "200" ]; then
    log_ok "Health check OK (HTTP $http_code)"
  else
    log_warn "Health check respondió HTTP $http_code (puede estar iniciando)"
  fi
}

# ============================================================
# ESPERAR ESTABILIDAD
# ============================================================

wait_stable() {
  log_info "Esperando que el deployment esté estable..."

  local max_wait=300
  local elapsed=0

  while [ $elapsed -lt $max_wait ]; do
    local state
    state=$(aws lightsail get-container-service-deployments \
      --service-name "$SERVICE_NAME" \
      --region "$AWS_REGION" \
      --query "deployments[0].state" \
      --output text 2>/dev/null)

    case "$state" in
      ACTIVE)
        log_ok "Deployment estable después de ${elapsed}s"
        return 0
        ;;
      FAILED)
        log_error "Deployment falló"
        return 1
        ;;
      *)
        log_info "Estado: $state (${elapsed}s / ${max_wait}s)"
        ;;
    esac

    sleep 10
    elapsed=$((elapsed + 10))
  done

  log_warn "Timeout esperando estabilidad (${max_wait}s)"
  return 1
}

# ============================================================
# FLUJO PRINCIPAL
# ============================================================

main() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Lightsail Container Service — AI Recruiter"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
  echo "  Service:  $SERVICE_NAME"
  echo "  Region:   $AWS_REGION"
  echo "  Image:    ${IMAGE_NAME}:${IMAGE_LABEL}"
  echo "  Port:     $CONTAINER_PORT"
  echo "  Health:   $HEALTH_CHECK_PATH"
  echo ""

  case "$ACTION" in
    status)
      check_status
      exit 0
      ;;
    endpoint)
      get_endpoint
      exit 0
      ;;
    deploy)
      validate_env
      create_service
      build_image
      push_image
      create_deployment
      wait_stable
      check_status
      get_endpoint
      ;;
  esac
}

main "$@"
