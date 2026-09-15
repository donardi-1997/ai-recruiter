# Playbook de Rollback Rápido — Canary DNS

## Variables

```bash
export REEMPLAZAR_HOSTED_ZONE_ID="REEMPLAZAR_AQUI"
export REEMPLAZAR_ALB_DNS="REEMPLAZAR_AQUI"
export REEMPLAZAR_ALB_HOSTED_ZONE_ID="REEMPLAZAR_AQUI"
export REEMPLAZAR_LIGHTSAIL_LB_DNS="REEMPLAZAR_AQUI"
export REEMPLAZAR_LIGHTSAIL_HOSTED_ZONE_ID="REEMPLAZAR_AQUI"
export REEMPLAZAR_DOMAIN="REEMPLAZAR_AQUI"
```

---

## Paso 1 — Revertir Route53 a 100% OLD

```bash
# Aplicar change-batch de rollback
aws route53 change-resource-record-sets \
  --hosted-zone-id "$REEMPLAZAR_HOSTED_ZONE_ID" \
  --change-batch file://infra/rollback-100-old.json

# Verificar que el cambio se aplicó
aws route53 list-resource-record-sets \
  --hosted-zone-id "$REEMPLAZAR_HOSTED_ZONE_ID" \
  --query "ResourceRecordSets[?Name=='api.${REEMPLAZAR_DOMAIN}.'].{Name:Name,SetIdentifier:SetIdentifier,Weight:Weight}" \
  --output table
```

## Paso 2 — Desactivar feature flag (alternativa)

```bash
# Si usas feature flag en frontend, desactivar via S3/Parameter Store
aws ssm put-parameter \
  --name "/ai-recruiter/USE_NEW_BACKEND" \
  --value "false" \
  --type String \
  --overwrite

# O via S3 (si el frontend lee de ahí)
aws s3 cp s3://REEMPLAZAR_AQUI/config.json s3://REEMPLAZAR_AQUI/config.json \
  --metadata '{"USE_NEW_BACKEND":"false"}' \
  --metadata-directive REPLACE
```

## Paso 3 — Verificar post-rollback

```bash
# 3.1 Health check OLD
curl -sf "https://api.${REEMPLAZAR_DOMAIN}/health" | python -m json.tool

# 3.2 Health check NEW (debe seguir respondiendo pero sin tráfico)
curl -sf "https://REEMPLAZAR_AQUI/health" | python -m json.tool

# 3.3 Smoke tests
OLD_BASE="https://api.${REEMPLAZAR_DOMAIN}" \
NEW_BASE="https://REEMPLAZAR_AQUI" \
JOB_ID="REEMPLAZAR_AQUI" \
python scripts/smoke_canary.py

# 3.4 Verificar logs CloudWatch (no errores nuevos)
aws logs filter-log-events \
  --log-group-name "/ecs/ai-recruiter-api" \
  --filter-pattern "ERROR" \
  --start-time $(($(date +%s) * 1000 - 600000)) \
  --region "$AWS_REGION" \
  --query "events | length(@)" \
  --output text
```

## Paso 4 — Escalar si persiste el problema

```bash
# Si el OLD backend tiene problemas después del rollback:
# 1. Verificar ECS tasks
aws ecs describe-services \
  --cluster ai-recruiter-cluster \
  --services ai-recruiter-api \
  --query "services[0].deployments[*].{Status:status,Running:runningCount}"

# 2. Escalar si es necesario
aws ecs update-service \
  --cluster ai-recruiter-cluster \
  --service ai-recruiter-api \
  --desired-count 3 \
  --region "$AWS_REGION"

# 3. Esperar estabilidad
aws ecs wait services-stable \
  --cluster ai-recruiter-cluster \
  --services ai-recruiter-api \
  --region "$AWS_REGION"
```

## Checklist de verificación

| # | Verificación | Comando | Estado |
|---|-------------|---------|--------|
| 1 | Route53 100% OLD | `list-resource-record-sets` | ☐ |
| 2 | Health OLD 200 | `curl /health` | ☐ |
| 3 | Health NEW 200 | `curl /health` | ☐ |
| 4 | Smoke tests OK | `smoke_canary.py` | ☐ |
| 5 | Logs sin errores | `filter-log-events ERROR` | ☐ |
| 6 | Tráfico normal | CloudWatch metrics | ☐ |
