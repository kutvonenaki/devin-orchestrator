# Assignment, strategy and original plan

> **Note:** this document captures the original brief, the strategic choices
> we made up front, and the implementation plan as it was *before* we started
> building. The final system (see the README and `architecture.md`) evolved
> during implementation — treat this as historical context, not current truth.

---

## 1. The assignment (sanitized brief)

Build a working end-to-end demo of an **event-driven automation using the
Devin API** that solves a concrete engineering workflow problem. Pitch the
solution as if presenting Devin to an engineering organization that already
runs a real codebase.

The evaluation explicitly weighs:

- Translating an ambiguous problem into a working system.
- Treating Devin as a **core primitive**, not just a helper.
- Communicating both technical execution and business impact.

### Three parts

**Part 1 — Select a use case.** The target codebase is
[`apache/superset`](https://github.com/apache/superset). Fork it and create
issues that the automation will remediate (bugs, dependency upgrades, quality
issues, etc.).

**Part 2 — Build the automation.** Use the
[Devin v3 API](https://docs.devin.ai/api-reference/overview) to build a
system that:

- Is triggered by an **event** (webhook, repo activity, ticket creation, or a
  scheduled poll).
- Programmatically creates and manages Devin sessions.
- Produces **observable outputs** for a technical audience — pull requests,
  status updates, dashboards, etc.

**Part 3 — Observability.** Add basic analytics so an engineering leader can
look at the system and answer *"how do I know this is working?"* — task
status, success/failure signals, throughput or progress tracking. Can be
lightweight (logs, simple metrics) but must be present.

### Deliverables

1. A **working project** where Devin successfully remediates the issues.
2. A short presentation (e.g. Loom video, slides) explaining the **what,
   how, why, and when**, pitched at a technical audience.
3. Two **GitHub repos**: the solution (Dockerized) and the forked target with
   the remediated issues.

### Suggested scenario (the one we picked)

> *"We've got hundreds of open issues across our monorepo. Most are
> small-to-medium bugs and feature requests that sit there for months
> because senior engineers are heads-down on platform work. Junior engineers
> spend more time understanding the issue than fixing it. We need a way to
> stop the bleeding."*

The team needs to go from a wall of stale issues to a system where things
actually get resolved — with the team kept in the loop as work happens.

---

## 2. Strategic choices

### The narrative
Instead of telling Devin exactly which file to fix, we **plant a vague bug
report** to force Devin to act as a *diagnostic engine* — find the cause,
fix it, prove the fix with a new test.

### The planted bug (Bug #1)
- **Location:** `superset/utils/pandas_postprocessing/compare.py` — the `PCT`
  branch (`(s_df - c_df) / c_df`) and the `ratio` branch (`s_df / c_df`).
- **Symptom (verified):** not a `ZeroDivisionError`. pandas `/0` silently
  yields `inf` / `NaN`, the chart-data JSON becomes invalid (`Infinity`), and
  the chart fails to render when a prior-period value is `0`.
- **Catch:** upstream `test_compare.py` has no zero-denominator case — we
  do *not* hand Devin the test. Devin must write its own.
- **Framing:** *"we planted a bug into our fork for Devin to find"* — never
  attribute it to a specific commit (the flaw also exists upstream).

### The second bug (Bug #2)
A second bug is staged but **no issue is created up front** — it lets the
demo show a fresh, live run starting from a clean slate. See
`planted_bug_2_cumulative.md` and `github_issues.md`.

### Observability
The orchestrator tracks every run as a JSON artifact and serves a live
dashboard. The key metric is **MTTR** (mean time to resolution) plus a
**run success rate** and (later) a **human-validated merge rate**.

To keep things self-contained, the dashboard is a server-rendered HTML page
served by the same FastAPI app — no JS framework, no separate frontend, no
external data store. Everything (poller + API + dashboard) runs inside a
single Docker container.

---

## 3. Original implementation plan

> The plan below was written before any code existed. Some details changed
> during implementation; the README and `architecture.md` reflect the final
> system.

### What we're building (one paragraph)
A self-contained service that watches the Superset fork for GitHub issues
labelled `devin`, hands each one to a Devin v3 session ("diagnose → fix →
write a test → open a PR"), tracks every run to disk as a JSON artifact,
posts the resulting PR link back on the issue, and serves a live dashboard
showing MTTR / success rate / throughput. One process, one container.

### End-to-end flow

```
GitHub issue opened + labelled `devin`
        │
   poller (every POLL_INTERVAL)  ──or──  POST /trigger {issue_number}
        │   github_client.list_open_issues("devin")
        │   store.exists("issue-<n>")?  ── yes ─► skip (dedup)
        ▼   no
   store.save_task(status=initializing, start_time)
        ▼
   devin_client.create_session(prompt + structured_output_schema)
   store.save_task(status=running, devin_session_id)
        ▼
   poll devin_client.get_session every DEVIN_POLL_INTERVAL
     until done (terminal OR structured_output populated) or timeout
        ▼
   success → save_task(completed, end_time, structured_output, pr)
             github_client.comment_on_issue(n, "Devin opened <pr_url> …")
   failure → save_task(failed, end_time, status_detail)
        ▼
   GET /  +  GET /api/tasks   render store.load_all() + metrics
```

### External APIs (verified)

**Devin v3** (`https://api.devin.ai/v3`, `Authorization: Bearer
$DEVIN_API_KEY`):
- `POST /v3/organizations/{org_id}/sessions` — body: `prompt`,
  `structured_output_schema` (JSON Schema Draft 7),
  `structured_output_required: true`, optional `title`, `tags`, `repos`,
  `idempotent`.
- `GET /v3/organizations/{org_id}/sessions/{session_id}` — `status` ∈ {new,
  claimed, running, exit, error, suspended, resuming}; `structured_output`
  holds the result, `pull_requests` the PR URLs.
- **Completion detection:** Devin often finishes the deliverable, populates
  `structured_output`, then idles at `status=running /
  status_detail=waiting_for_user` rather than reaching `exit`. So:
  - `is_done` = terminal status *or* `structured_output` has the PR URL.
  - `is_success` = `structured_output` has the PR URL and status isn't
    `error`.

**GitHub REST** (token-free where possible):
- `GET /repos/{owner}/{repo}/issues?state=open&labels={label}` — ⚠ returns
  PRs too, drop items containing `pull_request`.
- `GET /repos/{owner}/{repo}/pulls/{n}` — for PR state + merge tracking.
- `GET /repos/{owner}/{repo}/issues/{n}/comments` — for relaying review
  comments back into Devin sessions.
- `POST /repos/{owner}/{repo}/issues/{n}/comments` — comment-back (token
  required).
- Token is **optional** for reads on a public fork (60 req/hr unauth, fine
  at 3-min polling); set `GITHUB_TOKEN` to raise the limit and enable
  comment-back.

### Configuration (`.env`, pydantic-settings)

| Var | Default | Notes |
|---|---|---|
| `DEVIN_API_KEY` | required | Bearer token |
| `DEVIN_ORG_ID` | required | Path segment |
| `DEVIN_API_BASE` | `https://api.devin.ai/v3` | |
| `GITHUB_REPO` | required for live run | `owner/repo` |
| `GITHUB_TOKEN` | optional | unset → unauth reads + skip comment-back |
| `ISSUE_LABEL` | `devin` | The human gate |
| `POLL_INTERVAL_SECONDS` | `180` | Issue poll (slow on purpose, token-free) |
| `DEVIN_POLL_INTERVAL_SECONDS` | `60` | Session poll |
| `MAX_POLL_MINUTES` | `60` | Session timeout |
| `DATA_DIR` | `./data` | JSON store |

Fail fast on startup if any required var is missing. The pytest suite needs
no env/secrets — only the live demo reads credentials.

### Structured output schema (Devin's deliverable contract)

```json
{
  "type": "object",
  "properties": {
    "pr_url":             { "type": "string" },
    "root_cause_analysis":{ "type": "string" },
    "resolution_summary": { "type": "string" },
    "files_edited":       { "type": "array",  "items": {"type":"string"} },
    "file_changes":       { "type": "array",  "items": {
      "type":"object",
      "properties":{ "path":{"type":"string"}, "change_summary":{"type":"string"} },
      "required":["path","change_summary"]
    } },
    "test_command_run":   { "type": "string" },
    "test_stdout":        { "type": "string" }
  },
  "required": ["pr_url","root_cause_analysis","resolution_summary",
               "files_edited","file_changes","test_command_run","test_stdout"]
}
```

The unified diff is fetched authoritatively from the **GitHub PR** (not
Devin's self-report) — large escaped diffs are a common schema-validation
failure.

### Module map

| Module | Responsibility |
|---|---|
| `app/store.py` | JSON file store, atomic writes, metrics (MTTR / success / merge / throughput) |
| `app/devin_client.py` | Async Devin v3 client (create / poll / message) |
| `app/github_client.py` | Async GitHub client (issues, PR diff/status/comments) |
| `app/orchestrator.py` | Per-issue state machine: initializing → running → completed \| failed |
| `app/poller.py` | Scheduled GitHub-issue poll loop (dedup + label gate, bounded concurrency) |
| `app/pr_watcher.py` | (added later) Relay PR comments back to Devin; refresh PR merge state |
| `app/dashboard.py` | Server-rendered HTML dashboard, zero JS |
| `app/main.py` | FastAPI app, lifespan starts the poller |

### Trigger model
**Scheduled polling, not webhooks.** No public tunnel required, no HMAC,
runs anywhere, deterministic for demos. Webhooks are documented in the
README as the production upgrade — out of scope here.

### Testing
One suite, runs identically locally (conda) and inside the container. All
external calls mocked via `pytest-httpx`; no credentials needed. CI gate
is "all tests green in both environments." Live verification is a
**separate** step (`scripts/test_online.sh`) with real keys.

### Docker
Single-stage `python:3.11-slim` image. Secrets via `--env-file`,
`${DATA_DIR}` mounted (bind mount in the demo so data is visible on the
host). Image self-tests: `requirements.txt` includes pytest so
`docker run --rm img pytest -q` is part of the build verification.

### Risks & mitigations (as foreseen)

- **Devin run too slow for a short video** → record a pre-warmed dashboard
  view; narrate over a completed run; MTTR shown from real stored data.
- **Devin masks the symptom instead of fixing root cause** → prompt demands
  root-cause analysis + a new test; `test_stdout` is the visible proof.
- **GitHub list returns PRs as issues** → explicit `pull_request`-key
  filter, covered by a test.
- **Concurrent file writes** → atomic `os.replace`, one writer per file.
- **No GitHub token at demo** → unauth reads on a public fork + skip
  comment-back; Devin's PR "Fixes #N" still links the issue.
- **Secrets leakage** → `.env` gitignored; `.env.example` keys-only.

---

## 4. What ended up being different

These items moved during implementation — the final system in the README is
authoritative.

- **Merge rate** was added as a first-class metric (lagging, human-validated)
  next to run-success rate.
- **PR-comment relay** (`pr_watcher.py`) was added: review comments on the
  PR are forwarded back into the live Devin session so it pushes follow-up
  commits. Devin's bot replies are captured too.
- The orchestrator's "done" signal was tightened: `structured_output` is
  only treated as final when it contains a non-empty `pr_url` (Devin
  occasionally writes the dict partially).
- Polling cadence was deliberately *slowed* to 3 minutes for the GitHub side
  to stay comfortably within the unauthenticated rate limit.
- The dashboard added a lifecycle-aware status badge
  (`initializing → running → PR open → merged | PR closed | failed`) and
  showed Devin's reply under each relayed PR follow-up.
- `code_diff` was dropped from the structured-output contract — too prone
  to schema validation failures on large diffs — and fetched directly from
  the PR API instead.
