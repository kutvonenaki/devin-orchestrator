# Project: Devin autonomous issue solver

## What this is

A demo of how **Devin** can be used to auto-remediate GitHub issues: a
scheduled poller hands each labelled issue to a Devin v3 session
(diagnose → fix → test → open a PR), tracks every run as a JSON artifact, and
serves a live dashboard (run success · merge rate · MTTR · cost). Pitched to a
technical audience as "here's how an autonomous coding agent fits a real
workflow, and how a leader would know it's working."

Our deliverable is the **orchestrator** (FastAPI app + tests + Docker), which
lives in the project root — **never** inside `superset/`. Stack: Python 3.11,
FastAPI, `httpx`, `pytest`, Docker, JSON-file task store. Trigger = scheduled
issue polling + one-shot `/trigger` (no webhook). Tests are mandatory; keep it
Dockerized, env-var configured, and the dashboard clean/presentable.

`presentation/` holds the slides (`slides.md`, rendered `slides.pdf`,
`index.html`) — the live deck for the demo. `project_resources/` holds
`ASSIGNMENT_AND_PLAN.md` (original brief + plan), `architecture.md`
(current system in depth), and `github_issues.md` (planted-bug issue
texts for both bugs). README is the source of truth.

## ⚠️ `superset/` is NOT our codebase — ignore by default

`superset/` is a **vendored fork of apache/superset** (pushed to
`github.com/kutvonenaki/superset`) — the **target repo Devin operates on**,
not software we write. Treat as external/read-only:

- Don't search it for "the code", apply its conventions, or lint/refactor/
  format it.
- Don't follow `superset/CLAUDE.md`, `AGENTS.md`, `GPT.md`, `GEMINI.md` —
  those are upstream's, not authoritative here. **This file overrides them.**

## Planted bugs — leave both exactly as-is

Two bugs are intentionally planted in the fork for Devin to find from vague
reports. **Do not fix, guard, refactor, or "clean up" either** — the only
correct action in `superset/` is *none*.

1. **Bug #1** — unguarded divide-by-zero in
   `superset/utils/pandas_postprocessing/compare.py` (`PCT`:
   `(s_df - c_df) / c_df`, `ratio`: `s_df / c_df`). Symptom is **not** a
   `ZeroDivisionError`: pandas `/0` → `inf`/`NaN` → invalid chart-data JSON →
   chart won't render when a prior-period value is `0`. The issue text must
   describe that vague symptom, never a traceback. Proof harness:
   `scripts/repro_compare_bug.py` (outside `superset/` on purpose — we never
   hand Devin the test).
2. **Bug #2** — `.astype(int)` truncation in
   `superset/utils/pandas_postprocessing/cum.py` (cumulative/running total
   drops cents, compounds). **No issue created up front, by design** — the
   issue text is drafted in `project_resources/github_issues.md` and opened
   on demand via `scripts/create_bug2_issue.sh`.

Framing for the demo: "we planted a bug in our fork for Devin to find" — do
not attribute it to a specific commit (the flaw also exists upstream).
Upstream `test_compare.py` / `test_cum.py` have no zero/decimal cases, so
Devin's "write a new test" task is clean.

## Verified Devin API facts (v3 — do not assume v1)

- Base: `https://api.devin.ai/v3`, auth `Authorization: Bearer $DEVIN_API_KEY`.
- **Create:** `POST /v3/organizations/{org_id}/sessions` — body `prompt`,
  `structured_output_schema` (JSON Schema Draft 7), `structured_output_required`,
  optional `repos`, `title`, `tags`, `idempotent`. Returns `session_id`, `url`,
  `status`, `structured_output`.
- **Poll:** `GET /v3/organizations/{org_id}/sessions/{session_id}` —
  `status` ∈ {new, claimed, running, exit, error, suspended, resuming};
  `structured_output` holds the result, `pull_requests` the PR URLs. A
  successful run often idles at `status_detail=waiting_for_user` with output
  populated rather than reaching `exit` — treat output-present as done.

## Local dev & secrets

- Conda env **`devin-takehome`** (Python 3.11): `conda run -n devin-takehome <cmd>`.
- `.env` (gitignored) holds `DEVIN_API_KEY`, `DEVIN_ORG_ID`, `GITHUB_REPO`,
  `GITHUB_TOKEN`, `PORT`. Never commit secrets; `.env.example` has keys only.
- Run token-free (public fork → unauthenticated GitHub reads); don't reach for
  `GITHUB_TOKEN` — slow the polling if rate-limited.
