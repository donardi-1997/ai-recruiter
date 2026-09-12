#!/usr/bin/env bash
# ==============================================================
# deploy-lightsail-instances.sh — Desplegar AI Recruiter en
# Lightsail con instancias + Load Balancer
#
# Uso:
#   ./scripts/deploy-lightsail-instances.sh              # Deploy completo
#   ./scripts/deploy-lightsail-instances.sh --dry-run    # Solo comandos
#   ./scripts/deploy-lightsail-instances.sh --status     # Verificar
#   ./scripts/deploy-lightsail-instances.sh --ssh        # SSH a la instancia
#
# Requiere: AWS CLI, ssh-keygen (si no tiene key pair)
# ==============================================================

set -euo pipefail

# ============================================================
# CONFIGURACIÓN — REEMPLAZAR_AQUI
# ============================================================

AWS_REGION="${AWS_REGION:-REEMPLAZAR_AWS_REGION}"
AZ="${REEMPLAZAR_AZ:-REEMPLAZAR_AWS_REGIONa}"
INSTANCE_NAME="${REEMPLAZAR_INSTANCE_NAME:-ai-recruiter}"
BUNDLE="${REEMPLAZAR_BUNDLE:-small_2_0}"
BLUEPRINT="${REEMPLAZAR_BLUEPRINT:-ubuntu_20_04}"
IMAGE="${REEMPLAZAR_IMAGE:-ai-recruiter-api}"
IMAGE_TAG="${REEMPLAZAR_IMAGE_TAG:-latest}"
LB_NAME="${REEMPLAZAR_LB_NAME:-ai-recruiter-lb}"
KEY_PAIR="${REEMPLAZAR_KEY_PAIR:-REEMPLAZAR_AQUI}"
STATIC_IP="${REEMPLAZAR_STATIC_IP_NAME:-ai-recruiter-ip}"
PG_HOST="${REEMPLAZAR_PG_HOST:-REEMPLAZAR_AQUI}"
PG_DB="${REEMPLAZAR_PG_DB:-ai_recruiter}"
PG_USER="${REEMPLAZAR_PG_USER:-REEMPLAZAR_AQUI}"
PG_PASS="${REEMPLAZAR_PG_PASS:-REEMPLAZAR_AQUI}"

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

for arg in "$@"; do
  case $arg in
    --dry-run) DRY_RUN=true ;;
    --status)  ACTION="status" ;;
    --ssh)     ACTION="ssh" ;;
    --help|-h)
      echo "Uso: $0 [--dry-run|--status|--ssh]"
      exit 0
      ;;
  esac
done

# ============================================================
# USER DATA — Script de arranque
# ============================================================

generate_user_data() {
  cat << USERDATA
#!/bin/bash
set -euxo pipefail

# ── 1. Actualizar sistema ────────────────────────────────────
apt-get update -y
apt-get upgrade -y

# ── 2. Instalar Docker ───────────────────────────────────────
apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=\$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu \$(lsb_release -cs) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# ── 3. Habilitar Docker sin sudo ─────────────────────────────
usermod -aG docker ubuntu
systemctl enable docker
systemctl start docker

# ── 4. Login a ECR y descargar imagen ────────────────────────
AWS_REGION="${AWS_REGION}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-765761474007}"
ECR_REPO="${IMAGE}"
ECR_TAG="${IMAGE_TAG}"

aws ecr get-login-password --region "\$AWS_REGION" | \
  docker login --username AWS --password-stdin \
  "\${AWS_ACCOUNT_ID}.dkr.ecr.\${AWS_REGION}.amazonaws.com"

docker pull "\${AWS_ACCOUNT_ID}.dkr.ecr.\${AWS_REGION}.amazonaws.com/\${ECR_REPO}:\${ECR_TAG}"

# ── 5. Variables de entorno de la app ────────────────────────
export DATABASE_URL="${DATABASE_URL:-REEMPLAZAR_AQUI}"

# ── 6. Ejecutar contenedor ──────────────────────────────────
docker stop ai-recruiter 2>/dev/null || true
docker rm ai-recruiter 2>/dev/null || true

docker run -d \
  --name ai-recruiter \
  --restart unless-stopped \
  -p 80:80 \
  -e DATABASE_URL="\$DATABASE_URL" \
  -e AWS_REGION="\$AWS_REGION" \
  "\${AWS_ACCOUNT_ID}.dkr.ecr.\${AWS_REGION}.amazonaws.com/\${ECR_REPO}:\${ECR_TAG}"

# ── 7. Health check loop ─────────────────────────────────────
for i in \$(seq 1 30); do
  if curl -sf http://localhost/health > /dev/null 2>&1; then
    echo "✓ App arrancada correctamente"
    exit 0
  fi
  sleep 2
done
echo "WARNING: App no respondio health check en 60s"
USERDATA
}

# ============================================================
# VALIDACIONES
# ============================================================

validate_env() {
  local missing=()
  [ -z "$AWS_REGION" ]      && missing+=("REEMPLAZAR_AWS_REGION")
  [ -z "$INSTANCE_NAME" ]   && missing+=("REEMPLAZAR_INSTANCE_NAME")
  [ -z "$LB_NAME" ]         && missing+=("REEMPLAZAR_LB_NAME")
  [ -z "$IMAGE" ]           && missing+=("REEMPLAZAR_IMAGE")

  if [ ${#missing[@]} -gt 0 ]; then
    log_error "Variables faltantes:"
    for v in "${missing[@]}"; do
      echo "  export $v=REEMPLAZAR_AQUI"
    done
    exit 1
  fi

  if ! command -v aws &>/dev/null; then
    log_error "AWS CLI no encontrado"
    exit 1
  fi

  if ! aws sts get-caller-identity --region "$AWS_REGION" &>/dev/null; then
    log_error "Credenciales AWS no válidas"
    exit 1
  fi

  log_ok "Variables validadas"
}

# ============================================================
# PASO 1: KEY PAIR
# ============================================================

ensure_key_pair() {
  log_step "Paso 1: Key Pair"

  if aws lightsail get-key-pair --key-pair-name "$KEY_PAIR" --region "$AWS_REGION" &>/dev/null; then
    log_ok "Key pair '$KEY_PAIR' ya existe"
    return 0
  fi

  log_info "Creando key pair '$KEY_PAIR'..."

  if [ "$DRY_RUN" = true ]; then
    log_info "[DRY RUN] aws lightsail create-key-pair"
    return 0
  fi

  aws lightsail create-key-pair \
    --key-pair-name "$KEY_PAIR" \
    --region "$AWS_REGION" \
    --query "keyPair.privateKeyBase64" \
    --output text > ~/.ssh/${KEY_PAIR}.pem

  chmod 600 ~/.ssh/${KEY_PAIR}.pem
  log_ok "Key pair creado → ~/.ssh/${KEY_PAIR}.pem"
}

# ============================================================
# PASO 2: STATIC IP (opcional)
# ============================================================

ensure_static_ip() {
  log_step "Paso 2: Static IP (opcional)"

  if aws lightsail get-static-ip --static-ip-name "$STATIC_IP" --region "$AWS_REGION" &>/dev/null; then
    log_ok "Static IP '$STATIC_IP' ya existe"
    STATIC_IP_ADDR=$(aws lightsail get-static-ip \
      --static-ip-name "$STATIC_IP" \
      --region "$AWS_REGION" \
      --query "staticIp.ipAddress" \
      --output text)
    log_info "IP: $STATIC_IP_ADDR"
    return 0
  fi

  log_info "Creando static IP '$STATIC_IP'..."

  if [ "$DRY_RUN" = true ]; then
    log_info "[DRY RUN] aws lightsail create-static-ip"
    return 0
  fi

  STATIC_IP_ADDR=$(aws lightsail create-static-ip \
    --static-ip-name "$STATIC_IP" \
    --region "$AWS_REGION" \
    --query "staticIp.ipAddress" \
    --output text)

  log_ok "Static IP: $STATIC_IP_ADDR"
}

# ============================================================
# PASO 3: CREAR INSTANCIA
# ============================================================

create_instance() {
  log_step "Paso 3: Crear instancia Lightsail"

  if aws lightsail get-instance --instance-name "$INSTANCE_NAME" --region "$AWS_REGION" &>/dev/null; then
    log_warn "Instancia '$INSTANCE_NAME' ya existe — reutilizando"
    return 0
  fi

  log_info "Creando instancia '$INSTANCE_NAME' ($BLUEPRINT, $BUNDLE)..."

  if [ "$DRY_RUN" = true ]; then
    log_info "[DRY RUN] aws lightsail create-instances ..."
    return 0
  fi

  local user_data
  user_data=$(generate_user_data)

  aws lightsail create-instances \
    --instance-names "$INSTANCE_NAME" \
    --availability-zone "$AZ" \
    --blueprint-id "$BLUEPRINT" \
    --bundle-id "$BUNDLE" \
    --key-pair-name "$KEY_PAIR" \
    --user-data "$user_data" \
    --region "$AWS_REGION"

    log_info "Esperando que la instancia este activa (2-3 min)..."
  aws lightsail wait instance-active \
    --instance-name "$INSTANCE_NAME" \
    --region "$AWS_REGION"

  log_ok "Instancia '$INSTANCE_NAME' activa"
}

# ============================================================
# PASO 4: CREAR LOAD BALANCER
# ============================================================

create_load_balancer() {
  log_step "Paso 4: Crear Load Balancer"

  if aws lightsail get-load-balancer --load-balancer-name "$LB_NAME" --region "$AWS_REGION" &>/dev/null; then
    log_warn "LB '$LB_NAME' ya existe"
    return 0
  fi

  log_info "Creando Load Balancer '$LB_NAME'..."

  if [ "$DRY_RUN" = true ]; then
    log_info "[DRY RUN] aws lightsail create-load-balancer ..."
    return 0
  fi

  aws lightsail create-load-balancer \
    --load-balancer-name "$LB_NAME" \
    --instance-port 80 \
    --health-check-path "/" \
    --region "$AWS_REGION"

  log_info "Esperando que el LB este activo..."
  aws lightsail wait load-balancer-active \
    --load-balancer-name "$LB_NAME" \
    --region "$AWS_REGION"

  log_ok "Load Balancer '$LB_NAME' activo"
}

# ============================================================
# PASO 5: ADJUNTAR INSTANCIA AL LB
# ============================================================

attach_instance() {
  log_step "Paso 5: Adjuntar instancia al Load Balancer"

  if [ "$DRY_RUN" = true ]; then
    log_info "[DRY RUN] aws lightsail attach-load-balancer ..."
    return 0
  fi

  aws lightsail attach-load-balancer \
    --load-balancer-name "$LB_NAME" \
    --instance-name "$INSTANCE_NAME" \
    --region "$AWS_REGION"

  log_info "Esperando que la instancia este healthy..."
  aws lightsail wait load-balancer-active \
    --load-balancer-name "$LB_NAME" \
    --region "$AWS_REGION"

  log_ok "Instancia adjuntada al LB"
}

# ============================================================
# PASO 6: ASIGNAR STATIC IP AL LB
# ============================================================

assign_static_ip() {
  log_step "Paso 6: Asignar Static IP al LB"

  if [ -z "${STATIC_IP_ADDR:-}" ]; then
    log_info "Sin static IP — saltando"
    return 0
  fi

  if [ "$DRY_RUN" = true ]; then
    log_info "[DRY RUN] aws lightsail attach-static-ip ..."
    return 0
  fi

  # Obtener nombre de la instancia del LB
  local lb_instance
  lb_instance=$(aws lightsail get-load-balancer \
    --load-balancer-name "$LB_NAME" \
    --region "$AWS_REGION" \
    --query "loadBalancer.instanceHealthSummary[0].instanceName" \
    --output text)

  aws lightsail attach-static-ip \
    --static-ip-name "$STATIC_IP" \
    --instance-name "$lb_instance" \
    --region "$AWS_REGION"

  log_ok "Static IP $STATIC_IP_ADDR asignado a $lb_instance"
}

# ============================================================
# PASO 7: VERIFICAR ESTADO
# ============================================================

check_status() {
  log_step "Paso 7: Estado"

  if [ "$DRY_RUN" = true ]; then
    log_info "[DRY RUN] aws lightsail get-instances ..."
    return 0
  fi

  echo ""
  log_info "Instancia:"
  aws lightsail get-instances \
    --region "$AWS_REGION" \
    --query "instances[*].{Name:name,State:state,PublicIP:publicIpAddress,PrivateIP:privateIpAddress,Created:createdAt}" \
    --output table

  echo ""
  log_info "Load Balancer:"
  aws lightsail get-load-balancers \
    --region "$AWS_REGION" \
    --query "loadBalancers[*].{Name:loadBalancerName,State:state,DNS:dnsName,Health:healthReport}" \
    --output table

  echo ""
  log_info "Instancias en el LB:"
  aws lightsail get-load-balancer \
    --load-balancer-name "$LB_NAME" \
    --region "$AWS_REGION" \
    --query "loadBalancer.instanceHealthSummary[*].{Instance:instanceName,Status:state}" \
    --output table
}

# ============================================================
# PASO 8: OBTENER DNS / IP
# ============================================================

get_endpoint() {
  log_step "Paso 8: Endpoint"

  if [ "$DRY_RUN" = true ]; then
    log_info "[DRY RUN] aws lightsail get-load-balancers ..."
    return 0
  fi

  local dns
  dns=$(aws lightsail get-load-balancers \
    --region "$AWS_REGION" \
    --query "loadBalancers[?loadBalancerName=='${LB_NAME}'].dnsName | [0]" \
    --output text)

  if [ -z "$dns" ] || [ "$dns" = "None" ]; then
    log_error "No se pudo obtener el DNS del LB"
    return 1
  fi

  log_ok "Load Balancer DNS: $dns"
  echo ""
  echo "  HTTP:    http://$dns"
  echo "  Health:  http://$dns/health"
  echo "  API:     http://$dns/api/health"
  echo "  Docs:    http://$dns/docs"
  echo ""

  # Health check
  log_info "Verificando health..."
  local http_code
  http_code=$(curl -sf -o /dev/null -w "%{http_code}" "http://$dns/health" 2>/dev/null || echo "000")

  if [ "$http_code" = "200" ]; then
    log_ok "Health check OK (HTTP $http_code)"
  else
    log_warn "Health check respondio HTTP $http_code (puede estar iniciando)"
  fi

  if [ -n "${STATIC_IP_ADDR:-}" ]; then
    echo "  Static IP: $STATIC_IP_ADDR"
  fi
}

# ============================================================
# SSH
# ============================================================

ssh_instance() {
  log_step "SSH a instancia"

  local ip
  ip=$(aws lightsail get-instances \
    --region "$AWS_REGION" \
    --query "instances[?name=='${INSTANCE_NAME}'].publicIpAddress | [0]" \
    --output text)

  if [ -z "$ip" ] || [ "$ip" = "None" ]; then
    log_error "No se pudo obtener la IP publica"
    return 1
  fi

  log_info "Conectando a ubuntu@$ip ..."
  ssh -i ~/.ssh/${KEY_PAIR}.pem ubuntu@"$ip"
}

# ============================================================
# FLUJO PRINCIPAL
# ============================================================

main() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Lightsail Instances — AI Recruiter"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
  echo "  Instance: $INSTANCE_NAME"
  echo "  Bundle:   $BUNDLE"
  echo "  LB:       $LB_NAME"
  echo "  Image:    $IMAGE:$IMAGE_TAG"
  echo "  Region:   $AWS_REGION / $AZ"
  echo ""

  case "$ACTION" in
    status)   check_status; exit 0 ;;
    ssh)      ssh_instance; exit 0 ;;
    deploy)
      validate_env
      ensure_key_pair
      ensure_static_ip
      create_instance
      create_load_balancer
      attach_instance
      assign_static_ip
      check_status
      get_endpoint
      ;;
  esac
}

main "$@"
