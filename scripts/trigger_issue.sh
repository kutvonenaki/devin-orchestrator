#!/usr/bin/env bash
# One-shot manual trigger for a specific issue number (demo control / testing).
set -euo pipefail
if [ $# -lt 1 ]; then echo "usage: $0 <issue_number> [host]"; exit 1; fi
HOST="${2:-http://localhost:8000}"
curl -fsS -X POST "$HOST/trigger" \
  -H 'Content-Type: application/json' \
  -d "{\"issue_number\": $1}"
echo
