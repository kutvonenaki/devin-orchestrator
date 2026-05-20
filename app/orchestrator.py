"""Drive one issue through a Devin session and persist the result.

State machine: initializing -> running -> completed | failed.
Never raises out — a failed issue must not kill the poller.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from .devin_client import DevinAPIError
from .github_client import pr_number_from_url
from .store import Store, now_iso

log = logging.getLogger(__name__)

PROMPT_TEMPLATE = """You are an autonomous agent fixing a bug in the Apache \
Superset repository ({repo}).

The GitHub issue to resolve is #{number} ({issue_url}). Its full text is \
included below so you do NOT need to fetch it from GitHub:

--- ISSUE TITLE ---
{issue_title}
--- ISSUE BODY ---
{issue_body}
--- END ISSUE ---

Do the following:
1. From the symptom described above, investigate the codebase to find the \
root cause.
2. Fix the code.
3. Write a new unit test that fails before your fix and passes after it.
4. Run ONLY the new test file you created via the terminal and capture its \
output.
5. Open a Pull Request against {repo} that references the issue (include \
"Fixes #{number}" in the PR body).
6. For every file you changed, give a clear, specific per-file summary of \
what you changed and why (the actual code diff is read straight from the PR \
on GitHub — do NOT paste a git diff into the structured output).
7. Once the PR is open and the structured output is produced, you are done — \
finish and end the session. Do not wait for further input.
"""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pr_url": {"type": "string"},
        "root_cause_analysis": {
            "type": "string",
            "description": "The file and line of code causing the bug.",
        },
        "resolution_summary": {"type": "string"},
        "files_edited": {"type": "array", "items": {"type": "string"}},
        "file_changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "change_summary": {
                        "type": "string",
                        "description": (
                            "Specific description of what changed in this "
                            "file and why."
                        ),
                    },
                },
                "required": ["path", "change_summary"],
            },
            "description": "Per-file summary of what changed and why.",
        },
        "test_command_run": {"type": "string"},
        "test_stdout": {"type": "string"},
    },
    "required": [
        "pr_url",
        "root_cause_analysis",
        "resolution_summary",
        "files_edited",
        "file_changes",
        "test_command_run",
        "test_stdout",
    ],
}


def _pr_url(session: dict, output: dict) -> Optional[str]:
    if output.get("pr_url"):
        return output["pr_url"]
    prs = session.get("pull_requests") or []
    if prs:
        return prs[0].get("url") or prs[0].get("html_url")
    return None


async def _refresh_progress(task: dict, session: dict, devin, store: Store) -> None:
    """Mid-flight: surface Devin's latest activity + cost on the dashboard."""
    if session.get("acus_consumed") is not None:
        task["acus_consumed"] = session["acus_consumed"]
    try:
        messages = await devin.get_messages(task["devin_session_id"])
        latest = devin.latest_devin_message(messages)
        if latest:
            task["latest_message"] = latest
    except Exception as e:  # noqa: BLE001
        log.warning("get_messages (live) failed: %s", e)
    store.save_task(task)


async def _finalize_success(
    task: dict, session: dict, devin, github, store: Store
) -> None:
    output = session.get("structured_output") or {}
    task.update(
        status="completed",
        structured_output=output,
        pr_url=_pr_url(session, output),
        acus_consumed=session.get("acus_consumed", task.get("acus_consumed")),
        end_time=now_iso(),
    )
    store.save_task(task)

    # Authoritative diff straight from the PR (not Devin's self-report).
    pr_num = pr_number_from_url(task.get("pr_url"))
    if pr_num is not None:
        diff = await github.get_pr_diff(pr_num)
        if diff:
            task["code_diff"] = diff
    # Full worklog timeline for the dashboard detail.
    try:
        task["worklog"] = await devin.get_messages(task["devin_session_id"])
    except Exception as e:  # noqa: BLE001
        log.warning("get_messages (worklog) failed: %s", e)
    store.save_task(task)

    if task.get("pr_url"):
        try:
            await github.comment_on_issue(
                task["issue_number"],
                f"\U0001F916 Devin opened a fix: {task['pr_url']}",
            )
        except Exception as e:  # noqa: BLE001
            log.warning("comment_on_issue failed: %s", e)


async def _poll_until_done(
    task: dict, store: Store, devin, github, settings
) -> None:
    """Poll an existing Devin session to completion and persist the result."""
    deadline = time.monotonic() + settings.max_poll_minutes * 60
    while True:
        await asyncio.sleep(settings.devin_poll_interval_seconds)
        try:
            session = await devin.get_session(task["devin_session_id"])
        except DevinAPIError as e:
            log.warning("poll get_session failed, will retry: %s", e)
            if time.monotonic() > deadline:
                task.update(status="failed", error="timeout", end_time=now_iso())
                store.save_task(task)
                return
            continue
        if devin.is_done(session):
            break
        await _refresh_progress(task, session, devin, store)
        if time.monotonic() > deadline:
            task.update(status="failed", error="timeout", end_time=now_iso())
            store.save_task(task)
            return

    if devin.is_success(session):
        await _finalize_success(task, session, devin, github, store)
    else:
        task.update(
            status="failed",
            error=session.get("status_detail") or session.get("status"),
            acus_consumed=session.get("acus_consumed", task.get("acus_consumed")),
            end_time=now_iso(),
        )
        store.save_task(task)


async def resume_session(
    task: dict, store: Store, devin, github, settings
) -> None:
    """Re-attach to an in-flight Devin session after an orchestrator restart."""
    internal_id = task["internal_id"]
    session_id = task.get("devin_session_id")
    if not session_id:
        log.warning("resume_session: %s has no session_id, marking failed", internal_id)
        task.update(status="failed", error="lost session_id on restart", end_time=now_iso())
        store.save_task(task)
        return
    log.info("Resuming poll for %s (session %s)", internal_id, session_id)
    try:
        await _poll_until_done(task, store, devin, github, settings)
    except Exception as e:  # noqa: BLE001
        log.exception("resume_session failed for %s", internal_id)
        task.update(status="failed", error=str(e), end_time=now_iso())
        store.save_task(task)


async def process_issue(issue: dict, store: Store, devin, github, settings) -> None:
    number = issue["number"]
    internal_id = f"issue-{number}"
    if store.exists(internal_id):
        log.info("Skipping already-processed %s", internal_id)
        return

    task: dict[str, Any] = {
        "internal_id": internal_id,
        "issue_number": number,
        "issue_url": issue.get("html_url"),
        "issue_title": issue.get("title"),
        "issue_created_at": issue.get("created_at"),  # GitHub issue open date
        "status": "initializing",
        "devin_session_id": None,
        "devin_session_url": None,
        "start_time": now_iso(),
        "end_time": None,
        "pr_url": None,
        "structured_output": None,
        "code_diff": None,        # authoritative diff, fetched from the PR
        "worklog": None,          # Devin's message timeline (capped)
        "latest_message": None,   # live "what Devin is doing now"
        "acus_consumed": None,    # cost metric
        "pr_followups": [],       # PR review comments relayed back to Devin
        "pr_comments_synced_at": None,  # watcher high-water mark
        "pr_state": None,         # "open" | "closed" (refreshed by watcher)
        "pr_merged": False,       # True once a human merges the PR
        "pr_merged_at": None,     # ISO ts of the human merge
        "error": None,
    }
    store.save_task(task)

    try:
        repo = getattr(settings, "github_repo", None)
        prompt = PROMPT_TEMPLATE.format(
            repo=repo or "the target repository",
            number=number,
            issue_url=issue.get("html_url"),
            issue_title=issue.get("title") or "(no title)",
            issue_body=(issue.get("body") or "(no description provided)").strip(),
        )
        session = await devin.create_session(
            prompt=prompt,
            structured_output_schema=OUTPUT_SCHEMA,
            title=f"Fix: {issue.get('title')}"[:120],
            tags=["devin-takehome"],
            repos=[repo] if repo else None,
            # deterministic prompt per issue -> Devin returns the existing
            # session instead of creating a duplicate on a re-issued create
            idempotent=True,
        )
        task["devin_session_id"] = session.get("session_id")
        task["devin_session_url"] = session.get("url")
        task["status"] = "running"
        store.save_task(task)

        await _poll_until_done(task, store, devin, github, settings)
    except Exception as e:  # noqa: BLE001
        log.exception("process_issue failed for %s", internal_id)
        task.update(status="failed", error=str(e), end_time=now_iso())
        store.save_task(task)
