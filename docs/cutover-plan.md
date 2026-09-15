# Plan de Cutover — DynamoDB → PostgreSQL

## Variables del proyecto

```bash
export AWS_ACCOUNT_ID="765761474007"
export AWS_REGION="us-east-2"
export ECR_REPO="ai-recruiter"
export ECS_CLUSTER="ai-recruiter-cluster"
export ECS_SERVICE="ai-recruiter-api-v2"
export ECS_TASK_FAMILY="ai-recruiter-api"
export ECS_CONTAINER="Main"
export S3_FRONTEND="ai-recruiter-frontend-765761474007"
export CF_DISTRIBUTION="E1IBIX4EWENEP7"
export CF_DOMAIN="ai.adrianguerra.net"

# DynamoDB tables (source)
export DYNAMO_TABLES=(
  "ai-recruiter-candidates"
  "ai-recruiter-jobs"
  "ai-recruiter-evaluations"
  "ai-recruiter-job-candidates"
  "ai-recruiter-rankings"
)

# PostgreSQL (target)
export PG_HOST="REEMPLAZAR_AQUI"
export PG_PORT="5432"
export PG_DB="ai_recruiter"
export PG_USER="REEMPLAZAR_AQUI"
export PGPASSWORD="REEMPLAZAR_AQUI"

# S3 export bucket
export EXPORT_BUCKET="REEMPLAZAR_S3_BUCKET"
```

---

## Fase 0 — Pre-flight checks

```bash
# 0.1  Verificar que ECS está estable
aws ecs describe-services \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --region "$AWS_REGION" \
  --query "services[0].{Status:status,Desired:desiredCount,Running:runningCount,Deployments:deployments[*].{Status:status,Task:taskDefinition}}" \
  --output table

# 0.2  Verificar que CloudFront está online
aws cloudfront get-distribution \
  --id "$CF_DISTRIBUTION" \
  --query "Distribution.{Status:Status,Domain:DomainName,Enabled:DistributionConfig.Enabled}" \
  --output table

# 0.3  Verificarconnectividad a PostgreSQL
psql "host=$PG_HOST port=$PG_PORT dbname=$PG_DB user=$PG_USER" \
  -c "SELECT 1 AS alive;"

# 0.4  Verificar que las tablas existen en PostgreSQL
psql "host=$PG_HOST port=$PG_PORT dbname=$PG_DB user=$PG_USER" \
  -c "\dt REEMPLAZAR_DB_TABLE_*"

# 0.5  Crear S3 bucket para exports si no existe
aws s3api head-bucket --bucket "$EXPORT_BUCKET" 2>/dev/null || \
  aws s3api create-bucket \
    --bucket "$EXPORT_BUCKET" \
    --region "$AWS_REGION" \
    --create-bucket-configuration LocationConstraint="$AWS_REGION"

# 0.6  Snapshots de backup (DynamoDB point-in-time)
for TABLE in "${DYNAMO_TABLES[@]}"; do
  echo "Backup: $TABLE"
  aws dynamodb create-backup \
    --table-name "$TABLE" \
    --backup-name "${TABLE}-pre-cutover-$(date +%Y%m%d%H%M)" \
    --region "$AWS_REGION" \
    --query "BackupDetails.BackupArn" \
    --output text
done
```

---

## Fase 1 — Exportar DynamoDB a S3

### Opción A: Exportación nativa de DynamoDB (Point-in-Time)

```bash
# Exportar cada tabla como formato DynamoDB JSON
for TABLE in "${DYNAMO_TABLES[@]}"; do
  echo "=== Exporting $TABLE ==="

  EXPORT_ARN=$(aws dynamodb export-table-to-point-in-time \
    --table-name "$TABLE" \
    --s3-bucket "$EXPORT_BUCKET" \
    --s3-prefix "exports/$TABLE" \
    --export-format "DYNAMODB_JSON" \
    --region "$AWS_REGION" \
    --query "exportDescription.exportArn" \
    --output text)

  echo "  Export ARN: $EXPORT_ARN"
  echo "$TABLE=$EXPORT_ARN" >> /tmp/dynamo_exports.txt
done

# Verificar estado de exports (esperar COMPLETED)
while read -r LINE; do
  TABLE="${LINE%%=*}"
  ARN="${LINE#*=}"
  STATUS=$(aws dynamodb describe-export \
    --export-arn "$ARN" \
    --region "$AWS_REGION" \
    --query "exportDescription.exportStatus" \
    --output text)
  echo "$TABLE: $STATUS"
done < /tmp/dynamo_exports.txt

# Verificar archivos exportados
for TABLE in "${DYNAMO_TABLES[@]}"; do
  echo "=== Files for $TABLE ==="
  aws s3 ls "s3://$EXPORT_BUCKET/exports/$TABLE/" --recursive \
    --region "$AWS_REGION" | head -20
done
```

### Opción B: Exportación via AWS CLI (sin point-in-time)

```bash
# Scan completo → S3 (solo si la tabla es pequeña)
for TABLE in "${DYNAMO_TABLES[@]}"; do
  echo "=== Scanning $TABLE ==="

  # Contar ítems
  COUNT=$(aws dynamodb scan \
    --table-name "$TABLE" \
    --select COUNT \
    --region "$AWS_REGION" \
    --query "Count" \
    --output text)

  echo "  Total items: $COUNT"

  # Scan con paginación → JSON Lines en S3
  aws dynamodb scan \
    --table-name "$TABLE" \
    --region "$AWS_REGION" \
    --page-size 1000 \
    --output json | \
  jq -c '.Items[]' | \
  aws s3 cp - "s3://$EXPORT_BUCKET/exports/$TABLE/scan.jsonl" \
    --region "$AWS_REGION"

  echo "  Uploaded to s3://$EXPORT_BUCKET/exports/$TABLE/scan.jsonl"
done
```

---

## Fase 2 — Migrar datos a PostgreSQL

```bash
# 2.1  Ejecutar migration script
python -m pg_backend.migrate_dynamo_to_pg \
  --tables candidates jobs evaluations job_candidates rankings \
  --batch-size 1000 \
  --verbose

# 2.2  Verificar conteos (debe mostrar 0 diff para cada tabla)
python -c "
import os
from sqlalchemy import create_engine, text

engine = create_engine(os.getenv('DATABASE_URL', 'REEMPLAZAR_DB_URL'))
tables = [
    'REEMPLAZAR_DB_TABLE_CANDIDATES',
    'REEMPLAZAR_DB_TABLE_JOBS',
    'REEMPLAZAR_DB_TABLE_EVALUATIONS',
    'REEMPLAZAR_DB_TABLE_JOB_CANDIDATES',
    'REEMPLAZAR_DB_TABLE_RANKINGS',
]
with engine.connect() as conn:
    for t in tables:
        r = conn.execute(text(f'SELECT COUNT(*) FROM {t}'))
        print(f'{t}: {r.scalar()} rows')
"

# 2.3  Verificar integridad referencial
psql "host=$PG_HOST port=$PG_PORT dbname=$PG_DB user=$PG_USER" -c "
  -- Evaluations sin job válido
  SELECT COUNT(*) AS orphan_evaluations
  FROM REEMPLAZAR_DB_TABLE_EVALUATIONS e
  LEFT JOIN REEMPLAZAR_DB_TABLE_JOBS j ON j.job_id = e.job_id
  WHERE j.job_id IS NULL;

  -- Evaluations sin candidate válido
  SELECT COUNT(*) AS orphan_eval_candidates
  FROM REEMPLAZAR_DB_TABLE_EVALUATIONS e
  LEFT JOIN REEMPLAZAR_DB_TABLE_CANDIDATES c ON c.candidate_id = e.candidate_id
  WHERE c.candidate_id IS NULL;
"
```

---

## Fase 3 — (Opcional) Configurar AWS DMS

> Solo si se necesita replicación en vivo durante el cutover para no perder writes.

```bash
# 3.1  Crear DMS Replication Instance (si no existe)
aws dms create-replication-instance \
  --replication-instance-identifier ai-recruiter-dms \
  --replication-instance-class dms.t3.medium \
  --allocated-storage 50 \
  --vpc-security-group-ids sg-REEMPLAZAR_AQUI \
  --no-publicly-accessible \
  --region "$AWS_REGION"

# 3.2  Crear Source Endpoint (DynamoDB)
aws dms create-endpoint \
  --endpoint-identifier ai-recruiter-dynamo-source \
  --endpoint-type source \
  --engine-name dynamodb \
  --dynamodb-settings '{
    "ServiceAccessRoleArn": "arn:aws:iam::'$AWS_ACCOUNT_ID':role/ai-recruiter-dms-role"
  }' \
  --region "$AWS_REGION"

# 3.3  Crear Target Endpoint (PostgreSQL)
aws dms create-endpoint \
  --endpoint-identifier ai-recruiter-pg-target \
  --endpoint-type target \
  --engine-name postgres \
  --server-name "$PG_HOST" \
  --port "$PG_PORT" \
  --database-name "$PG_DB" \
  --username "$PG_USER" \
  --password "$PG_PASSWORD" \
  --region "$AWS_REGION"

# 3.4  Crear Replication Task
aws dms create-replication-task \
  --replication-task-identifier ai-recruiter-full-load \
  --source-endpoint-arn "$(aws dms describe-endpoints \
    --filters Name=endpoint-id,Values=ai-recruiter-dynamo-source \
    --query 'Endpoints[0].EndpointArn' --output text)" \
  --target-endpoint-arn "$(aws dms describe-endpoints \
    --filters Name=endpoint-id,Values=ai-recruiter-pg-target \
    --query 'Endpoints[0].EndpointArn' --output text)" \
  --replication-instance-arn "$(aws dms describe-replication-instances \
    --filters Name=replication-instance-id,Values=ai-recruiter-dms \
    --query 'ReplicationInstances[0].ReplicationInstanceArn' --output text)" \
  --migration-type full-load-and-cdc \
  --table-mappings '{
    "rules": [
      {
        "rule-type": "selection",
        "rule-id": "1",
        "rule-name": "all-tables",
        "object-locator": {
          "schema-name": "%",
          "table-name": "%"
        },
        "rule-action": "include"
      }
    ]
  }' \
  --region "$AWS_REGION"
```

---

## Fase 4 — Deploy backend a ECS (nueva imagen con PostgreSQL)

```bash
# 4.1  Login ECR
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin \
  "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# 4.2  Build imagen nueva
COMMIT_SHA=$(git rev-parse HEAD)
IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${COMMIT_SHA}"

docker build \
  --file Dockerfile \
  --tag "$IMAGE_URI" \
  --tag "${ECR_REPO}:latest" .

# 4.3  Push
docker push "$IMAGE_URI"
docker push "${ECR_REPO}:latest"

# 4.4  Renderizar task definition con nueva imagen
jq \
  --arg IMAGE "$IMAGE_URI" \
  --arg CONTAINER "$ECS_CONTAINER" \
  --arg DB_URL "$REEMPLAZAR_DB_URL" \
  --arg PG_HOST "$PG_HOST" \
  --arg PG_DB "$PG_DB" \
  '
  .containerDefinitions |=
  map(
    if .name == $CONTAINER
    then
      .image = $IMAGE |
      .environment += [
        {"name": "DATABASE_URL", "value": $DB_URL},
        {"name": "PG_HOST", "value": $PG_HOST},
        {"name": "PG_DB", "value": $PG_DB}
      ]
    else .
    end
  )
  ' \
  api-task-definition.json > api-task-definition-rendered.json

# 4.5  Registrar task definition
TASK_DEF_ARN=$(aws ecs register-task-definition \
  --cli-input-json file://api-task-definition-rendered.json \
  --region "$AWS_REGION" \
  --query "taskDefinition.taskDefinitionArn" \
  --output text)

echo "Registered: $TASK_DEF_ARN"

# 4.6  Actualizar ECS Service
aws ecs update-service \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --task-definition "$TASK_DEF_ARN" \
  --region "$AWS_REGION" \
  --query "service.{Status:status,Deployments:deployments[*].{Status:status,Task:taskDefinition,Running:runningCount}}"

# 4.7  Esperar estabilidad (timeout 10 min)
aws ecs wait services-stable \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --region "$AWS_REGION" && echo "✓ ECS stable" || echo "✗ TIMEOUT"

# 4.8  Verificar deployments
aws ecs describe-services \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --region "$AWS_REGION" \
  --query "services[0].deployments[*].{Status:status,Desired:desiredCount,Running:runningCount,Task:taskDefinition,LaunchType:launchType}" \
  --output table
```

---

## Fase 5 — Deploy frontend a S3 + CloudFront

```bash
# 5.1  Build frontend
cd frontend-react
npm ci
VITE_API_URL=/api npm run build
cd ..

# 5.2  Sync assets versionados (cache indefinido)
aws s3 sync frontend-react/dist/ "s3://$S3_FRONTEND" \
  --delete \
  --exclude "index.html" \
  --cache-control "public,max-age=31536000,immutable" \
  --region "$AWS_REGION"

# 5.3  Copiar index.html SIN cache
aws s3 cp frontend-react/dist/index.html "s3://$S3_FRONTEND/index.html" \
  --cache-control "no-cache,no-store,must-revalidate" \
  --content-type "text/html" \
  --region "$AWS_REGION"

# 5.4  Invalidar CloudFront
INVALIDATION_ID=$(aws cloudfront create-invalidation \
  --distribution-id "$CF_DISTRIBUTION" \
  --paths "/*" \
  --query "Invalidation.Id" \
  --output text)

echo "Invalidation: $INVALIDATION_ID"

# 5.5  Esperar invalidación
aws cloudfront wait invalidation-completed \
  --distribution-id "$CF_DISTRIBUTION" \
  --id "$INVALIDATION_ID" && echo "✓ CloudFront invalidation done"

# 5.6  Verificar
curl -sI "https://$CF_DOMAIN/" | head -5
curl -s "https://$CF_DOMAIN/api/health" | head -1
```

---

## Fase 6 — Checks post-deploy

```bash
# 6.1  Health check del API
curl -sf "https://$CF_DOMAIN/api/health" || \
  echo "FAIL: health endpoint unreachable"

# 6.2  Verificar que el API apunta a PostgreSQL
curl -s "https://$CF_DOMAIN/api/health" | python -m json.tool

# 6.3  Test end-to-end: listar jobs
curl -s -H "Authorization: Bearer $TEST_TOKEN" \
  "https://$CF_DOMAIN/api/jobs" | python -m json.tool | head -20

# 6.4  Test end-to-end: ranking endpoint
curl -s -H "Authorization: Bearer $TEST_TOKEN" \
  "https://$CF_DOMAIN/api/jobs/$TEST_JOB_ID/ranking" | python -m json.tool | head -20

# 6.5  Verificar CloudFront responses
curl -sI "https://$CF_DOMAIN/" | grep -E "^(HTTP|x-amz-cf|server)"
# Debe retornar 200 con headers de CloudFront

# 6.6  Verificar que el frontend carga correctamente
curl -s "https://$CF_DOMAIN/" | grep -o "<title>.*</title>"

# 6.7  Verificar logs de ECS (no errores recientes)
aws logs describe-log-streams \
  --log-group-name "/ecs/ai-recruiter-api" \
  --order-by LastEventTime \
  --descending \
  --limit 3 \
  --region "$AWS_REGION" \
  --query "logStreams[*].{Name:logStreamName,LastEvent:lastEventTime}" \
  --output table

# 6.8  Verificar errores en logs del último minuto
LOG_STREAM=$(aws logs describe-log-streams \
  --log-group-name "/ecs/ai-recruiter-api" \
  --order-by LastEventTime \
  --descending \
  --limit 1 \
  --region "$AWS_REGION" \
  --query "logStreams[0].logStreamName" \
  --output text)

aws logs filter-log-events \
  --log-group-name "/ecs/ai-recruiter-api" \
  --log-stream-names "$LOG_STREAM" \
  --filter-pattern "ERROR" \
  --start-time $(($(date +%s) * 1000 - 60000)) \
  --region "$AWS_REGION" \
  --query "events[*].message" \
  --output text
```

---

## Fase 7 — Rollback

### Rollback inmediato (< 5 min después del deploy)

```bash
# ROLLBACK 1: Revertir ECS al task definition anterior
PREV_TASK_DEF=$(aws ecs describe-services \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --region "$AWS_REGION" \
  --query "services[0].deployments[?status=='ACTIVE'].taskDefinition | [0]" \
  --output text)

echo "Reverting to: $PREV_TASK_DEF"

aws ecs update-service \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --task-definition "$PREV_TASK_DEF" \
  --region "$AWS_REGION"

aws ecs wait services-stable \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --region "$AWS_REGION"

echo "✓ ECS rolled back"
```

### Rollback de frontend (re-desplegar versión anterior)

```bash
# ROLLBACK 2: Restaurar frontend desde backup S3
# (Requiere haber hecho backup antes del deploy)
aws s3 sync "s3://$S3_FRONTEND-backup-pre-cutover/" "s3://$S3_FRONTEND/" \
  --region "$AWS_REGION"

aws cloudfront create-invalidation \
  --distribution-id "$CF_DISTRIBUTION" \
  --paths "/*"

echo "✓ Frontend rolled back"
```

### Rollback de datos (si PostgreSQL migration falló)

```bash
# ROLLBACK 3: Truncar tablas PG (los datos originales siguen en DynamoDB)
psql "host=$PG_HOST port=$PG_PORT dbname=$PG_DB user=$PG_USER" -c "
  TRUNCATE
    REEMPLAZAR_DB_TABLE_RANKING_ITEMS,
    REEMPLAZAR_DB_TABLE_RANKINGS,
    REEMPLAZAR_DB_TABLE_EVALUATIONS,
    REEMPLAZAR_DB_TABLE_JOB_CANDIDATES,
    REEMPLAZAR_DB_TABLE_CANDIDATES,
    REEMPLAZAR_DB_TABLE_JOBS
  CASCADE;
"

echo "✓ PostgreSQL truncated — DynamoDB remains untouched"
```

### Rollback de DMS (si configurado)

```bash
# ROLLBACK 4: Detener y eliminar DMS task
TASK_ARN=$(aws dms describe-replication-tasks \
  --filters Name=replication-task-id,Values=ai-recruiter-full-load \
  --query 'ReplicationTasks[0].ReplicationTaskArn' \
  --output text --region "$AWS_REGION")

aws dms stop-replication-task \
  --replication-task-arn "$TASK_ARN" \
  --region "$AWS_REGION"

aws dms delete-replication-task \
  --replication-task-arn "$TASK_ARN" \
  --region "$AWS_REGION"

echo "✓ DMS task deleted"
```

---

## Checklist resumen

| #  | Fase                          | Comando clave                                        | Éxito esperado              |
|----|-------------------------------|------------------------------------------------------|-----------------------------|
| 0  | Pre-flight                    | `ecs describe-services`                              | Running = Desired           |
| 1  | DynamoDB → S3                 | `dynamodb export-table-to-point-in-time`             | Status = COMPLETED          |
| 2  | S3 → PostgreSQL               | `python -m pg_backend.migrate_dynamo_to_pg`          | COUNT match = 0 diff        |
| 3  | (Opcional) DMS                | `dms create-replication-task`                        | Task status = Running       |
| 4  | Deploy ECS                    | `ecs update-service` + `wait services-stable`        | Running = 1, no error       |
| 5  | Deploy frontend               | `s3 sync` + `cloudfront create-invalidation`         | HTTP 200 on domain          |
| 6  | Post-deploy checks            | `curl /api/health`, logs sin ERROR                   | Health = OK                 |
| 7  | Rollback si falla             | `ecs update-service --task-definition PREV`          | Previous task restored      |
