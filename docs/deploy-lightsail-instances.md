# Despliegue en Lightsail Instances — AI Recruiter

## Variables de entorno

```bash
export REEMPLAZAR_AWS_REGION="us-east-2"
export REEMPLAZAR_AZ="us-east-2a"
export REEMPLAZAR_INSTANCE_NAME="ai-recruiter"
export REEMPLAZAR_BUNDLE="small_2_0"        # 2 vCPU, 4 GB RAM
export REEMPLAZAR_BLUEPRINT="ubuntu_20_04"
export REEMPLAZAR_IMAGE="ai-recruiter-api"
export REEMPLAZAR_IMAGE_TAG="latest"
export REEMPLAZAR_LB_NAME="ai-recruiter-lb"
export REEMPLAZAR_KEY_PAIR="ai-recruiter-key"
export REEMPLAZAR_STATIC_IP_NAME="ai-recruiter-ip"
export REEMPLAZAR_PG_HOST="REEMPLAZAR_AQUI"
export REEMPLAZAR_PG_DB="ai_recruiter"
export REEMPLAZAR_PG_USER="REEMPLAZAR_AQUI"
export REEMPLAZAR_PG_PASS="REEMPLAZAR_AQUI"
export DATABASE_URL="postgresql://${REEMPLAZAR_PG_USER}:${REEMPLAZAR_PG_PASS}@${REEMPLAZAR_PG_HOST}:5432/${REEMPLAZAR_PG_DB}"
```

---

## Script ejecutable

```bash
chmod +x scripts/deploy-lightsail-instances.sh
./scripts/deploy-lightsail-instances.sh              # Deploy completo
./scripts/deploy-lightsail-instances.sh --dry-run    # Solo mostrar comandos
./scripts/deploy-lightsail-instances.sh --status     # Verificar estado
./scripts/deploy-lightsail-instances.sh --ssh        # SSH a la instancia
```

---

## Comandos individuales (paso a paso)

### Paso 1 — Key Pair

```bash
# Crear key pair
aws lightsail create-key-pair \
  --key-pair-name REEMPLAZAR_KEY_PAIR \
  --region REEMPLAZAR_AWS_REGION \
  --query "keyPair.privateKeyBase64" \
  --output text > ~/.ssh/REEMPLAZAR_KEY_PAIR.pem

chmod 600 ~/.ssh/REEMPLAZAR_KEY_PAIR.pem
```

### Paso 2 — Static IP (opcional)

```bash
aws lightsail create-static-ip \
  --static-ip-name REEMPLAZAR_STATIC_IP_NAME \
  --region REEMPLAZAR_AWS_REGION

# Verificar IP asignada
aws lightsail get-static-ip \
  --static-ip-name REEMPLAZAR_STATIC_IP_NAME \
  --region REEMPLAZAR_AWS_REGION \
  --query "staticIp.ipAddress" \
  --output text
```

### Paso 3 — Crear instancia

```bash
# Generar user-data
cat > /tmp/user-data.sh << 'USERDATA'
#!/bin/bash
set -euxo pipefail

# Instalar Docker
apt-get update -y
apt-get upgrade -y
apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
usermod -aG docker ubuntu
systemctl enable docker
systemctl start docker

# Login ECR y descargar imagen
aws ecr get-login-password --region us-east-2 | \
  docker login --username AWS --password-stdin 765761474007.dkr.ecr.us-east-2.amazonaws.com
docker pull 765761474007.dkr.ecr.us-east-2.amazonaws.com/ai-recruiter-api:latest

# Ejecutar app
docker run -d \
  --name ai-recruiter \
  --restart unless-stopped \
  -p 80:80 \
  -e DATABASE_URL="REEMPLAZAR_AQUI" \
  -e AWS_REGION="us-east-2" \
  765761474007.dkr.ecr.us-east-2.amazonaws.com/ai-recruiter-api:latest

# Verificar
for i in $(seq 1 30); do
  curl -sf http://localhost/health && echo " OK" && exit 0
  sleep 2
done
USERDATA

# Crear instancia
aws lightsail create-instances \
  --instance-names REEMPLAZAR_INSTANCE_NAME \
  --availability-zone REEMPLAZAR_AZ \
  --blueprint-id ubuntu_20_04 \
  --bundle-id small_2_0 \
  --key-pair-name REEMPLAZAR_KEY_PAIR \
  --user-data file:///tmp/user-data.sh \
  --region REEMPLAZAR_AWS_REGION

# Esperar activa
aws lightsail wait instance-active \
  --instance-name REEMPLAZAR_INSTANCE_NAME \
  --region REEMPLAZAR_AWS_REGION
```

### Paso 4 — Crear Load Balancer

```bash
aws lightsail create-load-balancer \
  --load-balancer-name REEMPLAZAR_LB_NAME \
  --instance-port 80 \
  --health-check-path "/" \
  --region REEMPLAZAR_AWS_REGION

# Esperar activo
aws lightsail wait load-balancer-active \
  --load-balancer-name REEMPLAZAR_LB_NAME \
  --region REEMPLAZAR_AWS_REGION
```

### Paso 5 — Adjuntar instancia al LB

```bash
aws lightsail attach-load-balancer \
  --load-balancer-name REEMPLAZAR_LB_NAME \
  --instance-name REEMPLAZAR_INSTANCE_NAME \
  --region REEMPLAZAR_AWS_REGION

# Esperar que esté healthy
aws lightsail wait load-balancer-active \
  --load-balancer-name REEMPLAZAR_LB_NAME \
  --region REEMPLAZAR_AWS_REGION
```

### Paso 6 — Asignar Static IP al LB

```bash
# Obtener nombre de instancia del LB
LB_INSTANCE=$(aws lightsail get-load-balancer \
  --load-balancer-name REEMPLAZAR_LB_NAME \
  --region REEMPLAZAR_AWS_REGION \
  --query "loadBalancer.instanceHealthSummary[0].instanceName" \
  --output text)

aws lightsail attach-static-ip \
  --static-ip-name REEMPLAZAR_STATIC_IP_NAME \
  --instance-name "$LB_INSTANCE" \
  --region REEMPLAZAR_AWS_REGION
```

### Paso 7 — Verificar

```bash
# Estado
aws lightsail get-instances \
  --region REEMPLAZAR_AWS_REGION \
  --query "instances[*].{Name:name,State:state,IP:publicIpAddress}"

aws lightsail get-load-balancers \
  --region REEMPLAZAR_AWS_REGION \
  --query "loadBalancers[*].{Name:loadBalancerName,State:state,DNS:dnsName}"

# DNS del LB
DNS=$(aws lightsail get-load-balancers \
  --region REEMPLAZAR_AWS_REGION \
  --query "loadBalancers[0].dnsName" \
  --output text)

echo "DNS: $DNS"
curl -sf "http://$DNS/health"
```

### Paso 8 — SSH

```bash
ssh -i ~/.ssh/REEMPLAZAR_KEY_PAIR.pem ubuntu@REEMPLAZAR_AQUI

# Comandos útiles dentro de la instancia:
docker ps
docker logs ai-recruiter
docker exec -it ai-recruiter sh
curl http://localhost/health
```

---

## Rollback

```bash
# Eliminar LB y instancia
aws lightsail detach-load-balancer \
  --load-balancer-name REEMPLAZAR_LB_NAME \
  --region REEMPLAZAR_AWS_REGION

aws lightsail delete-load-balancer \
  --load-balancer-name REEMPLAZAR_LB_NAME \
  --region REEMPLAZAR_AWS_REGION

aws lightsail delete-instance \
  --instance-name REEMPLAZAR_INSTANCE_NAME \
  --region REEMPLAZAR_AWS_REGION

aws lightsail release-static-ip \
  --static-ip-name REEMPLAZAR_STATIC_IP_NAME \
  --region REEMPLAZAR_AWS_REGION
```

---

## Script ejecutable

```bash
#!/usr/bin/env bash
set -euo pipefail

# Configuración
AWS_REGION="REEMPLAZAR_AWS_REGION"
AZ="REEMPLAZAR_AZ"
INSTANCE="REEMPLAZAR_INSTANCE_NAME"
LB="REEMPLAZAR_LB_NAME"
KEY="REEMPLAZAR_KEY_PAIR"
IMAGE="765761474007.dkr.ecr.${AWS_REGION}.amazonaws.com/REEMPLAZAR_IMAGE:REEMPLAZAR_IMAGE_TAG"
DB_URL="REEMPLAZAR_AQUI"

echo "=== Paso 1: Key Pair ==="
aws lightsail create-key-pair --key-pair-name "$KEY" --region "$AWS_REGION" \
  --query "keyPair.privateKeyBase64" --output text > ~/.ssh/${KEY}.pem
chmod 600 ~/.ssh/${KEY}.pem

echo "=== Paso 2: Static IP ==="
IP=$(aws lightsail create-static-ip --static-ip-name ai-recruiter-ip \
  --region "$AWS_REGION" --query "staticIp.ipAddress" --output text)
echo "IP: $IP"

echo "=== Paso 3: Instancia ==="
USER_DATA=$(cat << 'EOF'
#!/bin/bash
set -euxo pipefail
apt-get update && apt-get upgrade -y
apt-get install -y docker.io
systemctl enable docker && systemctl start docker
usermod -aG docker ubuntu
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin 765761474007.dkr.ecr.us-east-2.amazonaws.com
docker pull 765761474007.dkr.ecr.us-east-2.amazonaws.com/ai-recruiter-api:latest
docker run -d --name app --restart unless-stopped -p 80:80 -e DATABASE_URL="REEMPLAZAR_AQUI" 765761474007.dkr.ecr.us-east-2.amazonaws.com/ai-recruiter-api:latest
EOF
)
aws lightsail create-instances --instance-names "$INSTANCE" --availability-zone "$AZ" \
  --blueprint-id ubuntu_20_04 --bundle-id small_2_0 --key-pair-name "$KEY" \
  --user-data "$USER_DATA" --region "$AWS_REGION"
aws lightsail wait instance-active --instance-name "$INSTANCE" --region "$AWS_REGION"

echo "=== Paso 4: Load Balancer ==="
aws lightsail create-load-balancer --load-balancer-name "$LB" \
  --instance-port 80 --region "$AWS_REGION"
aws lightsail wait load-balancer-active --load-balancer-name "$LB" --region "$AWS_REGION"

echo "=== Paso 5: Attach ==="
aws lightsail attach-load-balancer --load-balancer-name "$LB" \
  --instance-name "$INSTANCE" --region "$AWS_REGION"
aws lightsail wait load-balancer-active --load-balancer-name "$LB" --region "$AWS_REGION"

echo "=== Paso 6: DNS ==="
DNS=$(aws lightsail get-load-balancers --region "$AWS_REGION" \
  --query "loadBalancers[0].dnsName" --output text)
echo "URL: http://$DNS"
curl -sf "http://$DNS/health" && echo " ✓ Health OK"
```
