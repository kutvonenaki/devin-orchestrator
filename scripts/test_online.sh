#!/usr/bin/env bash
# Online connectivity checks — requires real credentials in .env.
# Does NOT start a full Devin fix session or open any PRs.
#
# Step 1: check_connections.py  — GitHub + Devin reachable & authenticated (free)
# Step 2: check_devin_repo.py   — Devin can clone the target repo (1 read-only session)
#
# Run AFTER scripts/test_offline.sh passes.
set -euo pipefail
cd "$(dirname "$0")/.."

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✅  $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️   $*${NC}"; }
fail() { echo -e "${RED}❌  $*${NC}"; exit 1; }
hdr()  { echo -e "\n${BOLD}━━━  $*  ━━━${NC}"; }

if [[ ! -f .env ]]; then
  fail ".env not found. Copy .env.example and fill in your credentials."
fi

hdr "STEP 1 — API connectivity check (free, no session created)"
echo "Verifying GitHub and Devin API are reachable and authenticated..."
echo ""
conda run --no-capture-output -n devin-takehome python -u scripts/check_connections.py
ok "Connections OK"

hdr "STEP 2 — Devin repo access check (~2–5 min, 1 read-only session)"
echo "Spinning up a read-only Devin session to confirm it can clone the repo."
echo "No PR will be opened. This is the last check before a real fix run."
echo ""
conda run --no-capture-output -n devin-takehome python -u scripts/check_devin_repo.py
ok "Devin can see the repo"

echo ""
echo -e "${BOLD}${GREEN}All online checks passed.${NC}"
echo "Ready for a live run:"
echo "  • Automatic: label a GitHub issue 'devin', then  uvicorn app.main:app --reload"
echo "  • One-shot:  conda run -n devin-takehome python scripts/run_once.py --issue N"
echo "  • Docker:    scripts/run-docker.sh"
