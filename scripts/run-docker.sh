#!/usr/bin/env bash
# Build the image, run the offline test suite inside it, then start the server.
# The server only starts if all tests pass — every deploy is self-verified.
set -euo pipefail
cd "$(dirname "$0")/.."

GREEN='\033[0;32m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✅  $*${NC}"; }
fail() { echo -e "${RED}❌  $*${NC}"; exit 1; }
hdr()  { echo -e "\n${BOLD}━━━  $*  ━━━${NC}"; }

hdr "STEP 1 — Build image"
docker build -t devin-orchestrator .
ok "Image built: devin-orchestrator"

hdr "STEP 2 — Run offline test suite inside the container"
echo "Running 53 mocked tests — no credentials needed (52 passed + 1 platform-skip is fine)..."
echo ""
docker run --rm \
  -e ORCH_DISABLE_POLLER=1 \
  devin-orchestrator \
  pytest -v --tb=short

ok "All tests passed inside the container"

hdr "STEP 3 — Connectivity check (GitHub + Devin APIs)"
echo "Verifying credentials and API reachability before starting the server..."
echo ""
if docker run --rm \
    --env-file .env \
    devin-orchestrator \
    python -u scripts/check_connections.py; then
  ok "All APIs reachable"
else
  fail "Connectivity check failed — fix credentials in .env before starting the server."
fi

hdr "STEP 4 — Start orchestrator"
echo "Dashboard → http://localhost:8000"
echo "Press Ctrl-C to stop."
echo ""
docker run --rm -it \
  --env-file .env \
  -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  devin-orchestrator
