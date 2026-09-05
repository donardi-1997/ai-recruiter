#!/usr/bin/env bash
# Idempotent canary apply script
set -euo pipefail
REGION="${REEMPLAZAR_AWS_REGION:-us-east-2}"
ZONE="${REEMPLAZAR_HOSTED_ZONE_ID:-REEMPLAZAR_AQUI}"

echo "Backup current records..."
aws route53 list-resource-record-sets --hosted-zone-id "$ZONE" --region "$REGION" > /tmp/route53-backup-$(date +%s).json

echo "Applying canary 90/10..."
aws route53 change-resource-record-sets --hosted-zone-id "$ZONE" --change-batch file://infra/canary-90-10.json --region "$REGION"

echo "Waiting for change to propagate (60s)..."
sleep 60

echo "Running smoke tests..."
OLD_BASE="https://api.REEMPLAZAR_DOMAIN" NEW_BASE="https://REEMPLAZAR_AQUI" JOB_ID="REEMPLAZAR_AQUI" python scripts/smoke_canary.py

echo "Done."
