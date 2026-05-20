#!/usr/bin/env bash
# Offline correctness gate — no credentials, no network, no ACUs.
# Runs the mocked pytest suite locally, then builds the Docker image and
# repeats the suite inside the container (packaging-parity check).
# Docker is optional: if the daemon is not running the step is skipped with
# a warning rather than a failure.
set -euo pipefail
cd "$(dirname "$0")/.."

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✅  $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️   $*${NC}"; }
fail() { echo -e "${RED}❌  $*${NC}"; exit 1; }
hdr()  { echo -e "\n${BOLD}━━━  $*  ━━━${NC}"; }

hdr "STEP 1 — Local pytest (conda env: devin-takehome)"
echo "Running 53 mocked tests — no credentials needed..."
echo "(In the container, 52 passed + 1 platform-skip is also a pass.)"
echo ""

ORCH_DISABLE_POLLER=1 conda run --no-capture-output -n devin-takehome \
  pytest -v --tb=short 2>&1

ok "Local suite passed"

hdr "STEP 2 — Docker image build + in-container pytest"
if ! docker info > /dev/null 2>&1; then
  warn "Docker daemon not running — skipping container parity check"
  echo "      Start Docker Desktop and re-run to verify packaging."
else
  echo "Building image devin-orchestrator..."
  docker build -t devin-orchestrator . 2>&1 | tail -5
  echo ""
  echo "Running pytest inside the container..."
  docker run --rm -e ORCH_DISABLE_POLLER=1 devin-orchestrator pytest -v --tb=short
  ok "Container suite passed (image is good)"
fi

echo ""
echo -e "${BOLD}${GREEN}All offline checks passed.${NC}"
echo "Next: run  scripts/test_online.sh  to verify real API connectivity."
