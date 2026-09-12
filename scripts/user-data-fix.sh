#!/bin/bash
# ==============================================================
# user-data-fix.sh — Remediacion manual para instancia Lightsail
#
# Ejecutar en la instancia como: sudo bash /tmp/user-data-fix.sh
#
# Requiere: AWS CLI pre-instalado o instalable, Docker
# ==============================================================

set -euo pipefail

LOG_FILE="/var/log/user-data-fix.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=========================================="
echo "  User-Data Fix — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=========================================="

# ============================================================
# CONFIGURACION
# ============================================================

AWS_REGION="${REEMPLAZAR_AWS_REGION:-us-east-2}"
AWS_ACCOUNT_ID="${REEMPLAZAR_AWS_ACCOUNT_ID:-765761474007}"
ECR_REPO="${REEMPLAZAR_IMAGE:-ai-recruiter-api}"
ECR_TAG="${REEMPLAZAR_IMAGE_TAG:-latest}"
CONTAINER_NAME="ai-recruiter"
CONTAINER_PORT=80
DATABASE_URL="${REEMPLAZAR_DATABASE_URL:-REEMPLAZAR_AQUI}"
MAX_PULL_RETRIES=3
PULL_BACKOFF=10

# ============================================================
# PASO 1: Instalar Docker si no existe
# ============================================================

echo "[1/6] Verificando Docker..."

if ! command -v docker &>/dev/null; then
    echo "Docker no encontrado — instalando..."
    apt-get update -y
    apt-get install -y docker.io
    systemctl enable docker
    systemctl start docker
    usermod -aG docker ubuntu
    echo "Docker instalado correctamente"
else
    echo "Docker ya instalado: $(docker --version)"
    # Asegurar que Docker esta corriendo
    if ! systemctl is-active --quiet docker; then
        echo "Iniciando Docker..."
        systemctl start docker
    fi
fi

# ============================================================
# PASO 2: Login a ECR
# ============================================================

echo "[2/6] Login a ECR..."

for i in $(seq 1 3); do
    echo "  Intento $i/3..."
    if aws ecr get-login-password --region "$AWS_REGION" | \
       docker login --username AWS --password-stdin \
       "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"; then
        echo "  Login ECR exitoso"
        break
    fi
    echo "  Login fallo, reintentando en ${PULL_BACKOFF}s..."
    sleep "$PULL_BACKOFF"
done

# Verificar que el login se guardo
if [ -f /home/ubuntu/.docker/config.json ]; then
    echo "  Docker config verificada"
else
    echo "  WARNING: Docker config no encontrada"
fi

# ============================================================
# PASO 3: Pull de imagen (con retries)
# ============================================================

echo "[3/6] Pull de imagen..."

IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${ECR_TAG}"

for i in $(seq 1 $MAX_PULL_RETRIES); do
    echo "  Intento $i/$MAX_PULL_RETRIES: docker pull $IMAGE_URI"
    if docker pull "$IMAGE_URI"; then
        echo "  Pull exitoso"
        break
    fi
    echo "  Pull fallo, reintentando en $((PULL_BACKOFF * i))s..."
    sleep $((PULL_BACKOFF * i))
done

# Verificar imagen
if docker image inspect "$IMAGE_URI" &>/dev/null; then
    echo "  Imagen verificada: $(docker image inspect "$IMAGE_URI" --format '{{.Id}}' | cut -c1-12)"
else
    echo "  ERROR: Imagen no disponible despues de reintentos"
    exit 1
fi

# ============================================================
# PASO 4: Detener y eliminar contenedor previo
# ============================================================

echo "[4/6] Limpiando contenedor previo..."

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "  Deteniendo contenedor existente..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    echo "  Contenedor previo eliminado"
else
    echo "  No hay contenedor previo"
fi

# ============================================================
# PASO 5: Ejecutar contenedor
# ============================================================

echo "[5/6] Ejecutando contenedor..."

docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    -p "${CONTAINER_PORT}:80" \
    -e DATABASE_URL="$DATABASE_URL" \
    -e AWS_REGION="$AWS_REGION" \
    -e LOG_LEVEL="INFO" \
    "$IMAGE_URI"

echo "  Contenedor iniciado"

# ============================================================
# PASO 6: Verificar salud
# ============================================================

echo "[6/6] Verificando salud..."

for i in $(seq 1 30); do
    if curl -sf http://localhost/health > /dev/null 2>&1; then
        echo "  Health check OK despues de ${i}s"
        curl -s http://localhost/health
        echo ""
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "  WARNING: Health check no respondio en 60s"
        echo "  Logs del contenedor:"
        docker logs "$CONTAINER_NAME" --tail 20
    fi
    sleep 2
done

echo ""
echo "=========================================="
echo "  Fix completado — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=========================================="
echo "  Contenedor: $(docker ps --filter "name=$CONTAINER_NAME" --format "{{.Status}}")"
echo "  Health:     $(curl -sf http://localhost/health || echo 'no disponible')"
echo "  Log:        $LOG_FILE"
