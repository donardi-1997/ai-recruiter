#!/bin/bash
set -eux
apt-get update -y && apt-get upgrade -y
apt-get install -y docker.io unzip curl
systemctl enable docker && systemctl start docker
usermod -aG docker ubuntu
curl -fsSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o /tmp/aws.zip && cd /tmp && unzip -q aws.zip && sudo ./aws/install
for i in 1 2 3; do
  aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin 765761474007.dkr.ecr.us-east-2.amazonaws.com && break
  sleep 10
done
for i in 1 2 3; do
  docker pull 765761474007.dkr.ecr.us-east-2.amazonaws.com/ai-recruiter-api:latest && break
  sleep $((10 * i))
done
docker rm -f ai-recruiter 2>/dev/null || true
docker run -d --name ai-recruiter --restart unless-stopped -p 80:80 -e DATABASE_URL='' 765761474007.dkr.ecr.us-east-2.amazonaws.com/ai-recruiter-api:latest
for i in $(seq 1 30); do curl -sf http://localhost/health && echo " OK" && exit 0; sleep 2; done
echo "WARNING: Health not ready"
