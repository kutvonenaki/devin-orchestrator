---
marp: true
theme: gaia
_class: lead
paginate: true
backgroundColor: #0d1117
color: #c9d1d9
style: |
  section {
    font-family: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background-color: #0d1117;
    color: #c9d1d9;
    padding: 60px 80px;
  }
  h1 {
    color: #58a6ff;
    font-weight: 700;
    font-size: 2.2em;
  }
  h2 {
    color: #58a6ff;
    border-bottom: 2px solid #30363d;
    padding-bottom: 12px;
    font-size: 1.8em;
  }
  footer {
    font-size: 0.6em;
    color: #8b949e;
  }
  a {
    color: #58a6ff;
    text-decoration: none;
  }
  table {
    font-size: 0.75em;
    margin-top: 20px;
    width: 100%;
    border-collapse: collapse;
    background-color: #161b22;
    border: 1px solid #30363d;
  }
  th {
    background-color: #21262d;
    color: #c9d1d9;
    font-weight: bold;
  }
  td, th {
    border: 1px solid #30363d;
    padding: 10px;
  }
  pre, code {
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
    background-color: #161b22;
    color: #ff7b72;
  }
  code {
    padding: 2px 6px;
    border-radius: 4px;
    background-color: #21262d;
    color: #f0f6fc;
  }
  ul, ol {
    margin-top: 15px;
    line-height: 1.6;
  }
  li {
    margin-bottom: 8px;
  }
  blockquote {
    border-left: 4px solid #30363d;
    padding-left: 15px;
    color: #8b949e;
    font-style: italic;
  }
---

# Devin Autonomous Issue Solver

Turning a stale GitHub backlog into reviewed PRs — automatically.

<br>
<small>Take-home Demo for Cognition</small>

---

## What is Devin?

**An autonomous software engineer**

- Works in its own containerized cloud environment
- Clones repo · reads code · edits · **runs tests in a real shell** · opens a PR
- You delegate a *whole ticket*, not a line of autocomplete code suggestions

---

## The cost of issues backlog

**Time solving + context switch.**

- **For each issue, an engineer must:**
  - Remember context, setup environment, diagnose, debug, fix, write tests
- **The Toll:**
  - Dropping deep work, wasted focus and time.
  - Lowered morale


---

## System Architecture

**FastAPI app polls inside docker.**

| Today (demo)              | In production           |
|---|---|
| Polling every 3 min       | GitHub webhook (instant) |
| JSON-file store           | Postgres (multi-replica) |
| Token-free public reads   | Service account / app token |
| Server-rendered HTML | Decoupled Next.js frontend|

- **Other** structured output schema → root cause, test command, test stdout. Diffs from Github PR

---

## Why Devin?

| | Human Flow | In-Editor Assistant | **Devin (This System)** |
|---|---|---|---|
| **Workspace Setup** | every time | every time | **none** |
| **Who Drives** | engineer | engineer | **autonomous** |
| **Context Switch** | yes | yes | **no — reviews finished PR** |
| **Parallel Issues** | no | no | **yes (multiple sessions)** |

- **Trust Through Transparency**: Shows root cause analysis and raw test outputs. Human owns the merge.
- **Integrations**: Acts as a private bug fixer for non-technical users (through Slack/Jira for example).

---
