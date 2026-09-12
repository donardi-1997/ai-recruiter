#!/usr/bin/env bash
# Cleanup post-cutover — generates safe commands (does NOT execute)
set -euo pipefail
REGION="${REEMPLAZAR_AWS_REGION:-us-east-2}"

echo "=== ECS Services ==="
aws ecs list-services --cluster ai-recruiter-cluster --region "$REGION" \
  --query "serviceArns[?contains(@,'ai-recruiter')]" --output table

echo ""
echo "=== DynamoDB Tables ==="
aws dynamodb list-tables --region "$REGION" \
  --query "TableNames[?contains(@,'ai-recruiter')]" --output table

echo ""
echo "=== IAM Roles ==="
aws iam list-roles --query "Roles[?contains(RoleName,'ai-recruiter')].{Name:RoleName,Arn:Arn}" --output table

echo ""
echo "Generated cleanup commands (review before executing):"
cat << 'EOF'
# ECS
# aws ecs update-service --cluster ai-recruiter-cluster --service SERVICE_NAME --desired-count 0
# aws ecs deregister-task-definition --task-definition TASK_DEF_ARN
# aws ecs delete-service --cluster ai-recruiter-cluster --service SERVICE_NAME

# DynamoDB (backup first!)
# aws dynamodb create-backup --table-name TABLE_NAME --backup-name pre-cleanup-$(date +%s)
# aws dynamodb delete-table --table-name TABLE_NAME

# IAM
# aws iam detach-role-policy --role-name ROLE_NAME --policy-arn POLICY_ARN
# aws iam delete-role --role-name ROLE_NAME
EOF
