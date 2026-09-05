#!/bin/bash
set -eux

apt-get update -y
apt-get install -y docker.io docker-compose-plugin postgresql postgresql-client
systemctl enable docker && systemctl start docker
usermod -aG docker ubuntu

# Configure PostgreSQL
su - postgres -c "psql -c \"CREATE DATABASE ai_recruiter;\""
su - postgres -c "psql -c \"ALTER USER postgres WITH PASSWORD 'postgres';\""
echo "listen_addresses = '*'" >> /etc/postgresql/16/main/postgresql.conf
echo "host all all 0.0.0.0/0 md5" >> /etc/postgresql/16/main/pg_hba.conf
systemctl restart postgresql

# Install AWS CLI
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/aws.zip
cd /tmp && unzip -q aws.zip && sudo ./aws/install
