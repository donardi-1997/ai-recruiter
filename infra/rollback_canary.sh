#!/usr/bin/env bash
# Rollback canary to 100% OLD
set -euo pipefail
REGION="${REEMPLAZAR_AWS_REGION:-us-east-2}"
ZONE="${REEMPLAZAR_HOSTED_ZONE_ID:-REEMPLAZAR_AQUI}"

echo "Rolling back to 100% OLD..."
aws route53 change-resource-record-sets --hosted-zone-id "$ZONE" --change-batch file://infra/rollback-100-old.json --region "$REGION"

echo "Waiting 60s for propagation..."
sleep 60

echo "Running minimal health checks..."
curl -sf "https://api.REEMPLAZAR_DOMAIN/health" || echo "WARNING: Health check failed"

echo "Waiting 5 minutes for full propagation..."
sleep 300

echo "Rollback complete."
