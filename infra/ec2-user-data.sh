#!/bin/bash
set -euo pipefail
dnf install -y python3.12 python3.12-pip unzip
mkdir -p /opt/ai-recruiter
aws s3 cp s3://ai-recruiter-frontend-765761474007/deploy/backend.zip /tmp/backend.zip
unzip -oq /tmp/backend.zip -d /opt/ai-recruiter
python3.12 -m pip install -r /opt/ai-recruiter/requirements.txt
cat >/etc/systemd/system/ai-recruiter.service <<'UNIT'
[Unit]
Description=AI Recruiter FastAPI
After=network-online.target

[Service]
WorkingDirectory=/opt/ai-recruiter
Environment=AWS_REGION=us-east-2
Environment=KNOWLEDGE_BASE_ID=VUGNMJQAEN
Environment=DATA_SOURCE_ID=P8SUL2VFHA
Environment=COGNITO_USER_POOL_ID=us-east-2_AkQ5UIW7R
Environment=COGNITO_CLIENT_ID=73ts1mbn3qla00uc15di6ihvju
ExecStart=/usr/local/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now ai-recruiter.service
