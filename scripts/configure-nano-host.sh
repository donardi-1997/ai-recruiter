#!/usr/bin/env bash
# Configure a 512 MiB Lightsail host for the AI Recruiter single-user runtime.
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "configure-nano-host.sh must run as root" >&2
  exit 1
fi

SWAPFILE="/swapfile"
SWAP_TARGET_BYTES=$((2 * 1024 * 1024 * 1024))

log() { printf '[nano-profile] %s\n' "$*"; }

configure_swap() {
  local current_swap
  current_swap=$(swapon --show=SIZE --bytes --noheadings 2>/dev/null | awk '{sum += $1} END {print sum + 0}')

  if (( current_swap < SWAP_TARGET_BYTES )); then
    log "Ensuring 2G swap at ${SWAPFILE}"
    if swapon --show=NAME --noheadings 2>/dev/null | grep -Fxq "$SWAPFILE"; then
      swapoff "$SWAPFILE"
    fi
    fallocate -l 2G "$SWAPFILE"
    chmod 600 "$SWAPFILE"
    mkswap "$SWAPFILE" >/dev/null
    swapon "$SWAPFILE"
  else
    log "Existing swap already meets the 2G target"
  fi

  if ! grep -Eq '^/swapfile[[:space:]]+none[[:space:]]+swap[[:space:]]' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi

  cat > /etc/sysctl.d/99-ai-recruiter-nano.conf <<'EOF'
vm.swappiness=10
EOF
  sysctl -p /etc/sysctl.d/99-ai-recruiter-nano.conf >/dev/null
}

configure_docker_logs() {
  log "Configuring Docker json-file log rotation"
  mkdir -p /etc/docker
  python3 - <<'PY'
import json
from pathlib import Path

path = Path('/etc/docker/daemon.json')
config = {}
if path.exists() and path.read_text(encoding='utf-8').strip():
    config = json.loads(path.read_text(encoding='utf-8'))

wanted = {
    "log-driver": "json-file",
    "log-opts": {
        "max-size": "10m",
        "max-file": "3",
    },
}
changed = False
for key, value in wanted.items():
    if config.get(key) != value:
        config[key] = value
        changed = True

rendered = json.dumps(config, indent=2, sort_keys=True) + "\n"
if not path.exists() or path.read_text(encoding='utf-8') != rendered:
    path.write_text(rendered, encoding='utf-8')
    Path('/run/ai-recruiter-docker-config-changed').touch()
PY

  if [[ -f /run/ai-recruiter-docker-config-changed ]]; then
    rm -f /run/ai-recruiter-docker-config-changed
    systemctl restart docker
  fi
}

configure_postgres() {
  if ! command -v psql >/dev/null 2>&1 || ! id postgres >/dev/null 2>&1; then
    log "PostgreSQL not installed yet; skipping database tuning"
    return 0
  fi

  log "Applying low-memory PostgreSQL settings"
  sudo -u postgres psql -v ON_ERROR_STOP=1 postgres <<'SQL'
ALTER SYSTEM SET shared_buffers = '64MB';
ALTER SYSTEM SET work_mem = '2MB';
ALTER SYSTEM SET maintenance_work_mem = '32MB';
ALTER SYSTEM SET effective_cache_size = '192MB';
ALTER SYSTEM SET max_connections = '20';
SQL
  systemctl restart postgresql
}

print_verification() {
  echo
  log "Memory and swap"
  free -h
  swapon --show

  echo
  log "Docker logging configuration"
  cat /etc/docker/daemon.json

  if command -v psql >/dev/null 2>&1 && id postgres >/dev/null 2>&1; then
    echo
    log "PostgreSQL low-memory settings"
    sudo -u postgres psql -At postgres -c \
      "SELECT name || '=' || setting || COALESCE(unit, '') FROM pg_settings WHERE name IN ('shared_buffers','work_mem','maintenance_work_mem','effective_cache_size','max_connections') ORDER BY name;"
  fi
}

configure_swap
configure_docker_logs
configure_postgres
print_verification
