# Devin autonomous issue solver

Turns a backlog of stale GitHub issues into reviewed pull requests,
automatically. A scheduled poller hands each labelled issue to a **Devin v3**
session (diagnose → fix → write a test → open a PR), tracks every run as a
JSON artifact, and serves a live dashboard (run success · merge rate · MTTR ·
cost). One process, one container — only Python and Docker.

📊 [Presentation slides](presentation/slides.pdf) ·
🏗 [Detailed architecture](project_resources/architecture.md)

---

## Quickstart (Docker)

```bash
cp .env.example .env          # fill DEVIN_API_KEY, DEVIN_ORG_ID, GITHUB_REPO
scripts/run-docker.sh         # build → run 53 tests → check connectivity → serve :8000
```

Dashboard → **http://localhost:8000**

To trigger a live Devin run with the included demo bug:

```bash
scripts/create_bug2_issue.sh  # creates and labels the issue on the fork
```

The running container polls GitHub every 3 minutes — the issue will be picked
up automatically and a Devin session starts without any further action.
Devin typically takes **15–30 minutes** to diagnose, fix, write a test, and
open a PR. Progress is visible on the dashboard in real time.

You can also add any issue manually; just make sure it has the `devin` label,
otherwise the poller will ignore it.

---

## How it works

```
GitHub issue (label: devin)            ← the label is the human gate
        │  poll every 3 min (token-free, public fork)
        ▼
Orchestrator ──► POST /v3/.../sessions  (deterministic prompt, idempotent)
                 structured output → pr_url, root cause, file summaries, test
        │  poll Devin every 60 s
        ▼
Session done ──► diff from the GitHub PR · worklog from Devin · task JSON
                 (atomic write) · comment the PR link back on the issue
        │
        ▼
Dashboard (GET /)  ── task JSONs → run success · merge rate · MTTR · ACUs

PR watcher (asyncio, every 3 min)
  • new human PR comment → relay into the live Devin session → follow-up commit
  • refresh PR merge state → drives the human-validated merge-rate metric
```

Restart-safe: on startup the app re-attaches to any in-flight Devin sessions
(`status: running`) — no lost work, no wasted ACUs.

---

## Project layout

```
app/
  config.py          pydantic-settings (env-based, fail-fast)
  devin_client.py    Devin v3 client: create/poll/message sessions, messages
  github_client.py   GitHub client: issues, comment, PR diff/comments/status
  orchestrator.py    per-issue state machine: initializing → running → completed|failed
  poller.py          asyncio issue poll loop (dedup, backlog, concurrency cap)
  pr_watcher.py      relays PR comments back to Devin + refreshes merge status
  store.py           JSON file store: atomic writes, metrics (success/merge/MTTR/ACU)
  dashboard.py       self-contained server-rendered HTML, zero JS
  main.py            FastAPI app: lifespan poller + PR watcher, /trigger, /healthz, /, /api/tasks

tests/               53 offline mocked tests — no credentials, no network
scripts/
  test_offline.sh       local pytest + Docker-parity run (the CI gate)
  test_online.sh        real-API reachability + 1 read-only Devin clone check
  run-docker.sh         production mode: build → test → connectivity → serve
  trigger_issue.sh      one-shot POST /trigger
  create_bug2_issue.sh  open the planted-bug-#2 issue on the fork (gh CLI)
  seed_demo_data.py     seed/clear sample dashboard rows for presentations
  check_connections.py  GitHub + Devin reachability (free, no session)
  check_devin_repo.py   verify Devin can clone the repo (1 read-only session)
  run_once.py           run the full pipeline once on a specific issue

project_resources/   ASSIGNMENT_AND_PLAN.md (brief + original plan),
                     architecture.md (current system), github_issues.md
                     (planted-bug issue texts for both bugs)
```

---

## Configure

```bash
cp .env.example .env          # fill DEVIN_API_KEY, DEVIN_ORG_ID, GITHUB_REPO
```

| Variable | Default | Purpose |
|---|---|---|
| `DEVIN_API_KEY` / `DEVIN_ORG_ID` | required | Devin v3 auth |
| `GITHUB_REPO` | required | `owner/repo` target |
| `GITHUB_TOKEN` | optional | only for PR comment-back; fork is public so reads are unauthenticated. Wrong token is worse than none — leave blank if unsure |
| `ISSUE_LABEL` | `devin` | label the poller acts on |
| `POLL_INTERVAL_SECONDS` | `180` | GitHub issue poll (slow on purpose: token-free) |
| `PR_COMMENT_POLL_INTERVAL_SECONDS` | `180` | GitHub PR comment/merge poll |
| `DEVIN_POLL_INTERVAL_SECONDS` | `60` | Devin session poll (hits Devin, not GitHub) |
| `MAX_POLL_MINUTES` | `60` | session timeout before marking failed |

---

## Testing — run in order

**Step 1 — Offline gate (no credentials, no network):**

```bash
scripts/test_offline.sh
```
Runs the **53 mocked tests** locally, then builds the Docker image and reruns
them inside the container (packaging parity; skipped with a warning if Docker
is down). Passes when both show `53 passed`. This is what CI/reviewers run.

**Step 2 — Online gate (needs real `.env`):**

```bash
scripts/test_online.sh
```
`check_connections.py` (free, seconds) then `check_devin_repo.py` (one
read-only ~2–5 min session, no PR). Both print ✅ on success.

**Step 3 — Live run:**

```bash
uvicorn app.main:app --reload                 # poller picks up labelled issues
conda run -n devin-takehome python scripts/run_once.py --issue N   # one-shot
scripts/run-docker.sh                          # build→test→connectivity→serve
```
Real sessions take 10–30 min, cost ACUs, open real PRs — run the offline +
online gates first.

**Step 4 — Second-bug demo (optional).** A second bug is already planted
(silent int-truncation in `superset/utils/pandas_postprocessing/cum.py`, a
different class from bug #1's divide-by-zero) with **no issue yet, by
design** — see `project_resources/github_issues.md`. With the app running:

```bash
scripts/create_bug2_issue.sh        # gh CLI (own keyring, not .env token); idempotent
scripts/trigger_issue.sh <issue#>   # optional: skip the 3-min poller wait
```

Triggering also works via `scripts/trigger_issue.sh <n>` (POST `/trigger`),
or set `ORCH_DISABLE_POLLER=1` to use `/trigger` exclusively in dev.

---

## Dashboard

`GET /` — server-rendered, auto-refreshes every 30 s. `GET /api/tasks` is the
same data as JSON.

**Metric cards:** Issues solved · Avg MTTR · Run success · Merged · ACUs Spent

- **Run success** = `completed / (completed + failed)` — of *finished* runs,
  the fraction that produced a PR. In-flight runs are excluded so the number
  is stable.
- **Merged** = `merged / completed` — the **human-validated** signal: a PR
  counts only once a person actually merged it. It's a *lagging* metric, so
  `pr_watcher` re-checks every resolved PR's state each cycle.
- Together they answer "how do you know it's working": Devin produces a
  reviewable PR (run success), and humans accept it (merge rate).

**Table:** Issue · Title · Created · Status · Session. The status badge is
lifecycle-aware — `initializing → running → failed`, or once a PR exists
`PR created → merged | PR closed`. Running rows show a live "what Devin is
doing now" line from the messages API.

**Expand a completed row:** root cause + resolution, per-file change
summaries, the authoritative unified diff (fetched from the GitHub PR, not
Devin's self-report), test command + stdout, relayed PR follow-ups, and the
full Devin worklog.

**Demo data:** `scripts/seed_demo_data.py` seeds sample rows (each carries a
`demo` badge but is counted in the metrics) for a populated presentation
view; `--clear` removes only those before a real run.

---

## Key design decisions

- **JSON file store, not SQLite.** One atomic file per issue under `data/`;
  the folder doubles as a raw artifact store. Scale path → Postgres.
- **Polling, not webhooks.** No public tunnel; runs anywhere; deterministic
  for demos. Webhooks are the documented production upgrade.
- **Diff from the GitHub PR API**, not Devin's structured output — large
  escaped diffs are a common schema-validation failure. Structured output
  stays narrative-only (root cause, summaries, test); the diff lives at the PR.
- **Idempotent session creation.** Deterministic prompt + `idempotent: true`,
  so a restart between "session created" and "result recorded" re-attaches to
  the existing session instead of spawning a duplicate (wasted ACUs / dup PR).
- **Token-free by design.** Public fork → unauthenticated reads; GitHub polls
  are deliberately slow (3 min) to stay under the rate limit.
- **Bounded concurrency** (asyncio semaphore, max 3) and **retry/backoff**
  (3× on 5xx/transport, linear) so transient blips never kill a session.
- **Human owns the merge.** Devin opens and iterates on PRs (including from
  relayed review comments) but never merges itself.
