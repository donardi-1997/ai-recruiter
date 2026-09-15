# Remediation — user-data failed on ai-recruiter-api-v2

## Quick Status

```bash
# Get instance IP
aws lightsail get-instance --instance-name ai-recruiter-api-v2 \
  --query 'instance.publicIpAddress' --output text --region us-east-2

# Get LB DNS
aws lightsail get-load-balancers --region us-east-2 \
  --query "loadBalancers[?loadBalancerName=='ai-recruiter-api-lb'].dnsName" --output text
```

## Step 1: SSH into instance

```bash
ssh -i ~/.ssh/ai-recruiter-lightsail-key2.pem ubuntu@18.227.10.153
```

## Step 2: Diagnose inside instance

```bash
# Check cloud-init logs
sudo journalctl -u cloud-init -b --no-pager | tail -n 200

# Check user-data output
sudo cat /var/log/cloud-init-output.log | tail -n 200

# Check Docker status
sudo systemctl status docker --no-pager

# Check containers
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"

# Check container logs if exists
docker logs ai-recruiter --tail 200 || echo "No container logs"

# Check ECR config
sudo ls -l /home/ubuntu/.docker/config.json || echo "No ECR config"
```

## Step 3: Fix manually

```bash
# Copy fix script from local
scp -i ~/.ssh/ai-recruiter-lightsail-key2.pem scripts/user-data-fix.sh \
  ubuntu@18.227.10.153:/tmp/user-data-fix.sh

# SSH and run
ssh -i ~/.ssh/ai-recruiter-lightsail-key2.pem ubuntu@18.227.10.153
sudo bash /tmp/user-data-fix.sh
```

## Step 4: Verify

```bash
# Inside instance
curl -sS http://localhost/health
docker ps --filter "name=ai-recruiter" --format "table {{.Names}}\t{{.Status}}"

# From outside
curl -sS http://ec7058c462f10c5cb66aa06e5f1a2b72-1077447159.us-east-2.elb.amazonaws.com/health
```

## Step 5: Generate report

```bash
# On instance
sudo bash -c 'cat > /tmp/manual_fix_report.md << EOF
# Manual Fix Report — $(date -u +%Y-%m-%dT%H:%M:%SZ)

## Status
- Instance: ai-recruiter-api-v2
- IP: $(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)
- Container: $(docker ps --filter name=ai-recruiter --format "{{.Status}}")
- Health: $(curl -sf http://localhost/health || echo "FAIL")

## Docker
$(docker ps -a --filter name=ai-recruiter --format "table {{.Names}}\t{{.Status}}\t{{.Image}}")

## Cloud-init (last 20 lines)
$(sudo journalctl -u cloud-init -b --no-pager | tail -n 20)

## Container logs (last 20 lines)
$(docker logs ai-recruiter --tail 20 2>&1)
EOF'

# Copy report locally
scp -i ~/.ssh/ai-recruiter-lightsail-key2.pem \
  ubuntu@18.227.10.153:/tmp/manual_fix_report.md \
  reports/manual_fix_$(date +%Y%m%d_%H%M%S).md
```

## Updated user-data (for future instances)

```bash
cat > user-data-v2.sh << 'USERDATA'
#!/bin/bash
set -euo pipefail
exec > >(tee /var/log/cloud-init-output.log) 2>&1

echo "=== Installing Docker ==="
apt-get update -y && apt-get upgrade -y
apt-get install -y docker.io
systemctl enable docker && systemctl start docker
usermod -aG docker ubuntu

echo "=== ECR Login ==="
for i in 1 2 3; do
    aws ecr get-login-password --region us-east-2 | \
      docker login --username AWS --password-stdin \
      765761474007.dkr.ecr.us-east-2.amazonaws.com && break
    sleep 10
done

echo "=== Pull image ==="
for i in 1 2 3; do
    docker pull 765761474007.dkr.ecr.us-east-2.amazonaws.com/ai-recruiter-api:latest && break
    sleep $((10 * i))
done

echo "=== Run container ==="
docker rm -f ai-recruiter 2>/dev/null || true
docker run -d --name ai-recruiter --restart unless-stopped -p 80:80 \
  -e DATABASE_URL="REEMPLAZAR_AQUI" \
  765761474007.dkr.ecr.us-east-2.amazonaws.com/ai-recruiter-api:latest

echo "=== Health check ==="
for i in $(seq 1 30); do
    curl -sf http://localhost/health && echo " OK" && exit 0
    sleep 2
done
echo "WARNING: Health not ready"
USERDATA
```
