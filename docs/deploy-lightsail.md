# Despliegue en Lightsail Container Service — AI Recruiter

## Variables de entorno

```bash
export REEMPLAZAR_AWS_REGION="us-east-2"
export REEMPLAZAR_SERVICE_NAME="ai-recruiter"
export REEMPLAZAR_IMAGE="ai-recruiter-api"
export REEMPLAZAR_IMAGE_LABEL="latest"

# Variables de la aplicación (se inyectan como env vars al contenedor)
export REEMPLAZAR_DB_URL="postgresql://REEMPLAZAR_AQUI:REEMPLAZAR_AQUI@REEMPLAZAR_AQUI:5432/REEMPLAZAR_AQUI"
```

---

## Script completo de despliegue

```bash
#!/usr/bin/env bash
set -euo pipefail

# ── Configuración ──────────────────────────────────────────────
AWS_REGION="REEMPLAZAR_AWS_REGION"
SERVICE="REEMPLAZAR_SERVICE_NAME"
IMAGE="REEMPLAZAR_IMAGE"
LABEL="REEMPLAZAR_IMAGE_LABEL"
PORT=80
HEALTH="/health"

# ── 1. Crear servicio ─────────────────────────────────────────
echo "Paso 1: Creando Lightsail Container Service..."
aws lightsail create-container-service \
  --service-name "$SERVICE" \
  --power small \
  --scale 1 \
  --region "$AWS_REGION"

echo "Esperando 30s para que el servicio esté listo..."
sleep 30

# ── 2. Construir imagen Docker ────────────────────────────────
echo "Paso 2: Construyendo imagen Docker..."
docker build --tag "${IMAGE}:${LABEL}" .

# ── 3. Push a Lightsail ──────────────────────────────────────
echo "Paso 3: Registrando imagen en Lightsail..."
aws lightsail push-container-image \
  --service-name "$SERVICE" \
  --label "$LABEL" \
  --image "${IMAGE}:${LABEL}" \
  --region "$AWS_REGION"

# ── 4. Crear deployment ───────────────────────────────────────
echo "Paso 4: Creando deployment..."
aws lightsail create-container-service-deployment \
  --service-name "$SERVICE" \
  --containers "{
    \"app\": {
      \":${LABEL}\",
      \"environment\": {
        \"DATABASE_URL\": \"${REEMPLAZAR_DB_URL}\"
      },
      \"ports\": {\"${PORT}\": \"HTTP\"}
    }
  }" \
  --public-endpoint "{
    \"containerName\": \"app\",
    \"containerPort\": ${PORT},
    \"healthCheck\": {
      \"healthyThreshold\": 2,
      \"unhealthyThreshold\": 3,
      \"timeoutSeconds\": 5,
      \"intervalSeconds\": 30,
      \"path\": \"${HEALTH}\",
      \"successCodes\": \"200\"
    }
  }" \
  --region "$AWS_REGION"

# ── 5. Esperar estabilidad ───────────────────────────────────
echo "Paso 5: Esperando deployment (máx 5 min)..."
for i in $(seq 1 30); do
  STATE=$(aws lightsail get-container-service-deployments \
    --service-name "$SERVICE" \
    --region "$AWS_REGION" \
    --query "deployments[0].state" \
    --output text)
  echo "  Estado: $STATE (${i}0s)"
  [ "$STATE" = "ACTIVE" ] && break
  [ "$STATE" = "FAILED" ] && echo "¡Deployment falló!" && exit 1
  sleep 10
done

# ── 6. Obtener endpoint ──────────────────────────────────────
echo "Paso 6: Endpoint público:"
URL=$(aws lightsail get-container-services \
  --service-name "$SERVICE" \
  --region "$AWS_REGION" \
  --query "containerServices[0].url" \
  --output text)

echo ""
echo "  URL:      $URL"
echo "  Health:   $URL$HEALTH"
echo "  API:      $URL/api/health"
echo "  Docs:     $URL/docs"
echo ""

# ── 7. Verificar health ──────────────────────────────────────
echo "Paso 7: Verificando health..."
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" "${URL}${HEALTH}" || echo "000")
[ "$HTTP_CODE" = "200" ] && echo "✓ Health OK" || echo "⚠ Health respondió HTTP $HTTP_CODE"
```

---

## Comandos individuales (paso a paso)

### Paso 1 — Crear servicio

```bash
aws lightsail create-container-service \
  --service-name REEMPLAZAR_SERVICE_NAME \
  --power small \
  --scale 1 \
  --region REEMPLAZAR_AWS_REGION

# Verificar
aws lightsail get-container-services \
  --service-name REEMPLAZAR_SERVICE_NAME \
  --region REEMPLAZAR_AWS_REGION \
  --query "containerServices[0].{Name:serviceName,State:state,Power:power}"
```

### Paso 2 — Build Docker

```bash
# Actualizar Dockerfile para el nuevo scaffold
cat > Dockerfile << 'DOCKERFILE'
FROM python:3.10-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY alembic.ini .
EXPOSE 80
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]
DOCKERFILE

docker build --tag REEMPLAZAR_IMAGE:REEMPLAZAR_IMAGE_LABEL .
docker images REEMPLAZAR_IMAGE
```

### Paso 3 — Push a Lightsail

```bash
aws lightsail push-container-image \
  --service-name REEMPLAZAR_SERVICE_NAME \
  --label REEMPLAZAR_IMAGE_LABEL \
  --image REEMPLAZAR_IMAGE:REEMPLAZAR_IMAGE_LABEL \
  --region REEMPLAZAR_AWS_REGION

# Verificar imágenes registradas
aws lightsail get-container-images \
  --service-name REEMPLAZAR_SERVICE_NAME \
  --region REEMPLAZAR_AWS_REGION \
  --query "images[*].{Image:image,Label:label,CreatedAt:createdAt}"
```

### Paso 4 — Crear deployment

```bash
aws lightsail create-container-service-deployment \
  --service-name REEMPLAZAR_SERVICE_NAME \
  --containers '{
    "app": {
      "image": ":REEMPLAZAR_IMAGE_LABEL",
      "environment": {
        "DATABASE_URL": "REEMPLAZAR_AQUI"
      },
      "ports": {
        "80": "HTTP"
      }
    }
  }' \
  --public-endpoint '{
    "containerName": "app",
    "containerPort": 80,
    "healthCheck": {
      "healthyThreshold": 2,
      "unhealthyThreshold": 3,
      "timeoutSeconds": 5,
      "intervalSeconds": 30,
      "path": "/health",
      "successCodes": "200"
    }
  }' \
  --region REEMPLAZAR_AWS_REGION
```

### Paso 5 — Verificar estado

```bash
# Estado del servicio
aws lightsail get-container-services \
  --service-name REEMPLAZAR_SERVICE_NAME \
  --region REEMPLAZAR_AWS_REGION \
  --query "containerServices[0].{State:state,Url:url}"

# Deployments
aws lightsail get-container-service-deployments \
  --service-name REEMPLAZAR_SERVICE_NAME \
  --region REEMPLAZAR_AWS_REGION \
  --query "deployments[0:3].{State:state,Containers:containers[].{Name:containerName,State:state}}"
```

### Paso 6 — Endpoint público

```bash
# Obtener URL
URL=$(aws lightsail get-container-services \
  --service-name REEMPLAZAR_SERVICE_NAME \
  --region REEMPLAZAR_AWS_REGION \
  --query "containerServices[0].url" \
  --output text)

echo "Endpoint: $URL"
echo "Health:   $URL/health"
echo "API:      $URL/api/health"
echo "Docs:     $URL/docs"

# Verificar health
curl -sf "$URL/health" | python -m json.tool
```

---

## Rollback

```bash
# Revertir a imagen anterior
aws lightsail create-container-service-deployment \
  --service-name REEMPLAZAR_SERVICE_NAME \
  --containers '{
    "app": {
      "image": ":REEMPLAZAR_IMAGE_LABEL",
      "environment": {
        "DATABASE_URL": "REEMPLAZAR_AQUI"
      },
      "ports": {
        "80": "HTTP"
      }
    }
  }' \
  --public-endpoint '{
    "containerName": "app",
    "containerPort": 80,
    "healthCheck": {
      "path": "/health",
      "successCodes": "200"
    }
  }' \
  --region REEMPLAZAR_AWS_REGION

# O eliminar el servicio completamente
aws lightsail delete-container-service \
  --service-name REEMPLAZAR_SERVICE_NAME \
  --region REEMPLAZAR_AWS_REGION
```

---

## Script ejecutable

```bash
chmod +x scripts/deploy-lightsail.sh
./scripts/deploy-lightsail.sh           # Deploy completo
./scripts/deploy-lightsail.sh --dry-run # Solo mostrar comandos
./scripts/deploy-lightsail.sh --status  # Verificar estado
./scripts/deploy-lightsail.sh --endpoint # Mostrar URL
```
