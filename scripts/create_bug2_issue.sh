#!/usr/bin/env bash
# Create the GitHub issue for PLANTED BUG #2 (cumulative / running-total
# int-truncation) on the fork, so the running orchestrator can resolve it.
#
# Why a script: bug #2 is planted in superset/ but intentionally has NO issue
# until we want the second demo (see project_resources/github_issues.md).
# Run this when the app (Docker or local) is up; the poller picks the issue up
# by its `devin` label on the next cycle.
#
# Auth: uses the `gh` CLI (its own keyring) — NOT the .env GITHUB_TOKEN. The
# app itself stays token-free; only this one-shot human action needs write
# access. Authenticate once with:  gh auth login
set -euo pipefail

REPO="${1:-${GITHUB_REPO:-kutvonenaki/superset}}"
TITLE="Cumulative / running-total columns don't tie out — YTD figures drift low"

if ! command -v gh >/dev/null 2>&1; then
  echo "❌ GitHub CLI (gh) not found. Install it, then: gh auth login" >&2
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "❌ gh is not authenticated. Run:  gh auth login" >&2
  exit 1
fi

# Idempotency: skip if an open issue with this exact title already exists.
EXISTING="$(gh issue list --repo "$REPO" --state open --search "$TITLE in:title" \
  --json number,title --jq ".[] | select(.title==\"$TITLE\") | .number" 2>/dev/null || true)"
if [ -n "$EXISTING" ]; then
  echo "ℹ️  Issue already open: #$EXISTING — $(gh issue view "$EXISTING" --repo "$REPO" --json url --jq .url)"
  exit 0
fi

# The poller filters on the `devin` label; ensure both labels exist (no-op if
# they already do — bug #1's issue created them).
gh label create devin --repo "$REPO" --color 5319e7 \
  --description "Auto-remediated by the Devin orchestrator" >/dev/null 2>&1 || true
gh label create bug --repo "$REPO" --color d73a4a \
  --description "Something isn't working" >/dev/null 2>&1 || true

URL="$(gh issue create --repo "$REPO" --title "$TITLE" \
  --label devin --label bug --body-file - <<'BODY'
Our finance dashboards use "running total" / cumulative columns (YTD revenue,
cumulative bookings, etc.). The numbers look plausible but they don't
reconcile: the final YTD figure is consistently a bit **lower** than the
straight sum of the monthly values, and the gap gets worse the more rows are
in the series.

**What we see**
- Affects charts/tables using the cumulative ("running total") post-processing.
- Whole-number test data looks fine; the discrepancy shows up on real monetary
  amounts (values with cents).
- The bigger the date range / the more data points, the larger the shortfall —
  looks like a small per-row rounding/truncation that compounds.
- No error in the UI or logs; the values are just wrong, so it went unnoticed
  until Finance cross-checked YTD against the raw sum.

**Steps to reproduce**
1. Build a chart with a metric that has fractional values (e.g., revenue with
   cents).
2. Enable the cumulative / running-total post-processing (sum).
3. Compare the last cumulative value to the plain sum of the column — they
   differ, and the difference grows with row count.

**Impact:** Cumulative finance numbers can't be trusted for board/finance
reporting. We need the running total to preserve fractional precision.

_Environment: latest `master`._
BODY
)"

echo "✅ Created: $URL"
ISSUE_NUM="${URL##*/}"
echo
echo "Next:"
echo "  • The poller will pick it up automatically within POLL_INTERVAL_SECONDS"
echo "    (default 180s / 3 min). Watch the dashboard at http://localhost:8000"
echo "  • Or trigger it immediately:"
echo "      scripts/trigger_issue.sh $ISSUE_NUM"
