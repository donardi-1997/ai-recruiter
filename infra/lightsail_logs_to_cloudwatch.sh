#!/usr/bin/env bash
# Forward Docker logs from Lightsail instance to CloudWatch
set -euo pipefail

LOG_GROUP="${REEMPLAZAR_LOG_GROUP:-ai-recruiter-lightsail}"
CONTAINER="${REEMPLAZAR_CONTAINER:-ai-recruiter}"
REGION="${REEMPLAZAR_AWS_REGION:-us-east-2}"

echo "Installing CloudWatch agent..."
sudo apt-get update -y && sudo apt-get install -y amazon-cloudwatch-agent

sudo tee /opt/aws/amazon-cloudwatch-agent/etc/config.json > /dev/null << EOF
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/docker/${CONTAINER}-json.log",
            "log_group_name": "${LOG_GROUP}",
            "log_stream_name": "{instance_id}",
            "retention_in_days": 7
          }
        ]
      }
    }
  }
}
EOF

sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -s -c file:/opt/aws/amazon-cloudwatch-agent/etc/config.json

echo "Done. Log group: ${LOG_GROUP}"
