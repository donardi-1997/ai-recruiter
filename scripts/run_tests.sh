#!/usr/bin/env bash
# ==============================================================
# run_tests.sh — Ejecutar tests localmente (backend + frontend)
#
# Uso:
#   ./scripts/run_tests.sh              # Todos los tests
#   ./scripts/run_tests.sh backend      # Solo backend
#   ./scripts/run_tests.sh frontend     # Solo frontend
#   ./scripts/run_tests.sh contract     # Solo contract tests
# ==============================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; exit 1; }

# ── Backend ─────────────────────────────────────────────────

run_backend() {
  echo "━━━ Backend tests ━━━"
  cd "$ROOT_DIR"

  export DATABASE_URL="sqlite:///:memory:"

  echo "Installing deps..."
  pip install -q -r requirements.txt pytest alembic 2>/dev/null

  echo "Syntax check..."
  python -m py_compile app/main.py
  python -m py_compile app/models.py
  python -m py_compile app/crud.py
  python -m py_compile app/deps.py
  pass "Syntax OK"

  echo "Running pytest..."
  python -m pytest app/tests/ -v --tb=short
  pass "Backend tests passed"
}

# ── Contract tests ──────────────────────────────────────────

run_contract() {
  echo "━━━ Contract tests ━━━"
  cd "$ROOT_DIR"
  export DATABASE_URL="sqlite:///:memory:"
  python -m pytest app/tests/test_contract.py -v --tb=short
  pass "Contract tests passed"
}

# ── Frontend ────────────────────────────────────────────────

run_frontend() {
  echo "━━━ Frontend tests ━━━"
  cd "$ROOT_DIR/frontend-react"

  echo "Installing deps..."
  npm ci --silent 2>/dev/null

  echo "Lint..."
  npm run lint
  pass "Lint OK"

  echo "Tests..."
  npm test
  pass "Frontend tests passed"

  echo "Build..."
  VITE_API_URL=/api npm run build
  pass "Build OK"
}

# ── Main ────────────────────────────────────────────────────

case "${1:-all}" in
  backend)  run_backend ;;
  contract) run_contract ;;
  frontend) run_frontend ;;
  all)
    run_backend
    run_contract
    run_frontend
    ;;
  *)
    echo "Usage: $0 [backend|contract|frontend|all]"
    exit 1
    ;;
esac

echo ""
pass "All checks passed!"
