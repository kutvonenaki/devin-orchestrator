# Architecture (current implementation)

This document describes the **system as it actually exists** — not the
original plan (that's `ASSIGNMENT_AND_PLAN.md`). The README is the canonical
user-facing reference; this is the deeper technical view.

---

## 1. One process, one container

```
┌─────────────────────────── single Docker container ───────────────────────────┐
│                                                                               │
│   FastAPI (uvicorn)                                                           │
│                                                                               │
│   ┌────────────────────────────────────────────────────────────────────────┐  │
│   │  lifespan startup                                                       │  │
│   │    ├─► poller.poll_loop          (every 180s, GitHub issues)            │  │
│   │    └─► pr_watcher.pr_comment_loop (every 180s, PR comments + merge)     │  │
│   └────────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│   ┌──────────────┐   ┌────────────────┐   ┌────────────────┐                  │
│   │  HTTP routes │   │ orchestrator   │   │  JSON store    │                  │
│   │   GET  /     │   │ per-issue FSM  │◄─►│  ./data/*.json │                  │
│   │   GET  /api  │   │ initializing→  │   │  atomic writes │                  │
│   │   POST /trig │   │ running→ done  │   └────────────────┘                  │
│   │   GET /heal  │   └────────────────┘                                       │
│   └──────────────┘            │                                               │
│          ▲                    │                                               │
│          │                    ▼                                               │
│          │            ┌──────────────┐   ┌───────────────┐                    │
│          │            │ devin_client │   │ github_client │                    │
│          │            │  httpx async │   │  httpx async  │                    │
│          │            └──────┬───────┘   └───────┬───────┘                    │
└──────────│───────────────────│───────────────────│────────────────────────────┘
           │                   │                   │
        browser           Devin v3 API        GitHub REST API
       (zero JS)
```

Everything lives in `app/` (~8 modules, ~1000 LOC). The dashboard is
server-rendered HTML — no React, no separate frontend, no build step.

---

## 2. State machine — per issue

```
                  POST /trigger  or  poller picks up labelled issue
                                      │
                              ┌───────▼────────┐
                              │ initializing   │ (task JSON written)
                              └───────┬────────┘
                                      │ create Devin session (idempotent)
                              ┌───────▼────────┐
                              │   running      │ (devin_session_id stored)
                              └───────┬────────┘
                                      │ poll every 60s
                  ┌───────────────────┼───────────────────┐
                  │                   │                   │
       has_output(session)         timeout            status=error
       AND pr_url present
                  │                   │                   │
          ┌───────▼────────┐  ┌───────▼────────┐  ┌───────▼────────┐
          │   completed    │  │     failed     │  │     failed     │
          │ + pr_url       │  │ error=timeout  │  │ error=detail   │
          │ + structured   │  └────────────────┘  └────────────────┘
          │ + code_diff    │                       (pr_watcher then
          │ + worklog      │                        tracks any merge)
          └────────────────┘
```

**Completion detection** is the subtle bit. Devin frequently finishes its
deliverable, writes `structured_output`, and then **idles at
`status=running, status_detail=waiting_for_user`** instead of reaching
`status=exit`. So we don't gate on `status==exit` alone — we gate on
"`pr_url` present in `structured_output`". A partial structured output
(e.g. only `root_cause_analysis` filled in) is *not* treated as done; that
race was a real bug we hit and fixed.

---

## 3. The two background loops

### 3.1 Issue poller (`app/poller.py`)
- Runs every `POLL_INTERVAL_SECONDS` (default 180).
- `github.list_open_issues(label)` — filters PRs out of the issues feed.
- Dedup: skip any issue where `store.exists(f"issue-{n}")` is true.
- Each new issue → `asyncio.create_task(orchestrator.process_issue(...))`
  under an `asyncio.Semaphore(3)` cap.
- Polls **first**, then waits — so the first poll fires immediately on
  container startup.
- Best-effort: a transient GitHub error is logged and the loop continues.

### 3.2 PR watcher (`app/pr_watcher.py`)
- Runs every `PR_COMMENT_POLL_INTERVAL_SECONDS` (default 180).
- For every task that's `completed` with a `pr_url` and a session ID, and
  **not a demo row**:
  - **Forward new human comments** from the PR back into the Devin session
    (`devin.send_message(...)`). Dedup by `comment_id`; skip bot comments;
    advance a `pr_comments_synced_at` high-water mark.
  - **Match Devin's bot reply** for each relayed comment by scanning all PR
    comments and taking the first bot reply that came after the human one.
    Stored as `devin_reply` on the followup so the dashboard can show
    Devin's response under each comment.
  - **Refresh PR merge state** (`github.get_pr_status`). Persist
    `pr_state`, `pr_merged`, `pr_merged_at` if anything changed.

The merge-rate metric on the dashboard is **lagging by design** — a human
can merge days later — so the watcher re-checks every resolved PR each
cycle.

---

## 4. JSON store (`app/store.py`)

One file per issue: `${DATA_DIR}/issue-<n>.json`. Atomic writes via
`tempfile` + `os.replace()` on the same filesystem. One writer per file
(the orchestrator processing that issue), readers (dashboard / metrics)
never block.

```json
{
  "internal_id": "issue-1",
  "issue_number": 1,
  "issue_url": "https://github.com/...",
  "issue_title": "...",
  "issue_created_at": "2026-05-19T09:41:12Z",
  "status": "completed",
  "devin_session_id": "...",
  "devin_session_url": "...",
  "start_time": "...",
  "end_time": "...",
  "pr_url": "https://github.com/.../pull/3",
  "structured_output": {
    "pr_url": "...",
    "root_cause_analysis": "...",
    "resolution_summary": "...",
    "files_edited": ["..."],
    "file_changes": [{ "path": "...", "change_summary": "..." }],
    "test_command_run": "...",
    "test_stdout": "..."
  },
  "code_diff": "diff --git ...",
  "worklog": [ { "source": "...", "message": "...", "created_at": ... } ],
  "latest_message": "...",
  "acus_consumed": 0.0,
  "pr_followups": [
    {
      "comment_id": 1234,
      "user": "reviewer",
      "body": "Please also guard NaN",
      "created_at": "...",
      "forwarded_at": "...",
      "devin_reply": "Addressed in c2388a2 — added .fillna(0) ..."
    }
  ],
  "pr_comments_synced_at": "...",
  "pr_state": "open",
  "pr_merged": false,
  "pr_merged_at": null,
  "error": null
}
```

### Metrics
Computed in-Python on every dashboard request from `load_all()`:

| Metric | Formula |
|---|---|
| **Issues solved** | `len(completed)` |
| **Avg MTTR** | `mean(end_time - start_time)` over completed tasks, in minutes |
| **Run success** | `completed / (completed + failed)` (in-flight excluded for stability) |
| **Merged %** | `merged / completed` — **the human-validated metric** |
| **ACUs Spent** | `sum(acus_consumed)` over all tasks |

Demo rows (`"demo": true`) are counted in the metrics but tagged in the
dashboard so it's transparent which rows are seeded vs. live.

---

## 5. Devin v3 client (`app/devin_client.py`)

Async `httpx`. One shared `AsyncClient`. Bearer auth. Retries 3× on 5xx /
transport errors with linear backoff (transient blips never kill a session).

**Sessions are idempotent.** `idempotent=True` on create, combined with a
deterministic prompt (built from the issue number + title + body) means a
restart between "session created" and "result recorded" re-attaches to the
existing session instead of spawning a duplicate (wasted ACUs / duplicate
PR).

Key methods:
- `create_session(prompt, structured_output_schema, title, tags, repos, idempotent)`
- `get_session(session_id)` — also exposes `pull_requests` and
  `acus_consumed`.
- `get_messages(session_id)` — drives the "what Devin is doing now" live
  field plus the full worklog on completion.
- `send_message(session_id, message)` — the PR-comment relay path.
- Static helpers: `is_terminal`, `has_output` (gated on `pr_url`),
  `is_done`, `is_success`.

---

## 6. GitHub client (`app/github_client.py`)

Async `httpx`. **Token is optional** — no header is sent when
`GITHUB_TOKEN` is unset. With no token, reads on a public fork work but
the unauthenticated rate limit is 60 req/hr; the 3-min polling cadence
keeps us comfortably under that.

- `list_open_issues(label)` — filters PRs out of the issues feed.
- `get_issue(n)`
- `get_pr_diff(n)` — authoritative diff (not Devin's self-report).
- `get_pr_status(n)` — `{state, merged, merged_at}` for the merge-rate
  metric.
- `list_pr_comments(n, since=...)` — for the PR watcher.
- `comment_on_issue(n, body)` — no-op when no token.

---

## 7. Dashboard (`app/dashboard.py`)

Server-rendered single HTML page, refreshes every 30 s via meta-refresh.
Zero JS, no external assets.

**Cards (top):** Issues solved · Avg MTTR · Run success · Merged · ACUs
Spent.

**Status badge** is lifecycle-aware:
`initializing → running → failed`, or once a PR exists
`PR open → merged | PR closed`.

**Table:** Issue · Title · Created · Status · Session.

**Expand a completed row →** root cause + resolution, per-file change
summaries, the authoritative unified diff (fetched from the PR), test
command + stdout, PR follow-ups with **Devin's reply** under each, and the
full Devin worklog.

---

## 8. Key design decisions (with reasoning)

| Decision | Why |
|---|---|
| **Polling over webhooks** | No public tunnel, runs anywhere, deterministic for demos. Webhooks are the documented production upgrade. |
| **JSON files over SQLite** | Demo scale; folder doubles as raw-artifact store. Scale path → Postgres. |
| **Idempotent sessions** | Deterministic prompt + `idempotent: true` survives restarts mid-run without duplicating Devin sessions or PRs. |
| **Diff from PR API, not Devin output** | Large escaped diffs are a common schema-validation failure. Structured output stays narrative-only. |
| **`pr_url` gates "done"** | Partial structured output is real (we hit it). Treating "any output" as done led to incomplete saves. |
| **Token-free by default** | Public fork → unauthenticated reads. Polling is deliberately slow to stay under the rate limit. |
| **Bounded concurrency + retry** | 3-task semaphore + 3× linear backoff on 5xx so transient blips don't kill a run. |
| **Human owns the merge** | Devin opens and iterates on PRs (incl. relayed review comments) but never merges itself. The merge-rate metric is the human-validated signal. |
| **Demo rows counted, badged** | Seeded data ships in `data/` so reviewers see a populated dashboard; the badge makes it transparent which rows are real. |

---

## 9. What's intentionally **out of scope**

- Webhooks (would need a public tunnel; polling is enough for a demo).
- Auth / RBAC on the dashboard (single-user demo).
- Postgres / multi-replica state (JSON files don't scale, but they're
  trivially atomic and observable; production path noted).
- Live tailing of Devin sessions via SSE / websockets — the
  `latest_message` field on each polled cycle is sufficient for the
  dashboard.
- Slack / Jira integration — written up in the slides as the next step.
