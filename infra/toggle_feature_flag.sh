#!/usr/bin/env bash
# Toggle USE_NEW_BACKEND feature flag
set -euo pipefail

MODE="${1:-off}"
REGION="${REEMPLAZAR_AWS_REGION:-us-east-2}"

case "$MODE" in
  on)
    echo "Enabling USE_NEW_BACKEND..."
    aws ssm put-parameter --name "/ai-recruiter/USE_NEW_BACKEND" --value "true" --type String --overwrite --region "$REGION"
    aws cloudfront create-invalidation --distribution-id "REEMPLAZAR_CF_DISTRIBUTION" --paths "/*" --region "$REGION"
    echo "Done. Feature flag ON."
    ;;
  off)
    echo "Disabling USE_NEW_BACKEND..."
    aws ssm put-parameter --name "/ai-recruiter/USE_NEW_BACKEND" --value "false" --type String --overwrite --region "$REGION"
    aws cloudfront create-invalidation --distribution-id "REEMPLAZAR_CF_DISTRIBUTION" --paths "/*" --region "$REGION"
    echo "Done. Feature flag OFF."
    ;;
  *)
    echo "Usage: $0 [on|off]"
    exit 1
    ;;
esac
