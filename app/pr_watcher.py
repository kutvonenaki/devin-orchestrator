"""Watch the PRs of resolved issues and forward new human comments to Devin.

Closes the loop: an engineer reviews the PR Devin opened, leaves a comment
("also guard NaN"), and that comment is relayed straight into the still-open
Devin session — which wakes from ``waiting_for_user`` and pushes a follow-up
commit. No webhook, no public URL: a second asyncio loop alongside the issue
poller.

Best-effort throughout: a flaky GitHub/Devin call for one task is logged and
skipped — it never crashes the loop or any other task.
"""

from __future__ import annotations

import asyncio
import logging

from .github_client import pr_number_from_url
from .store import Store, now_iso

log = logging.getLogger(__name__)


def _eligible(task: dict) -> bool:
    """A task we can relay PR comments for: Devin finished and opened a PR,
    and its session is still addressable. Demo rows are skipped — their
    issue/PR numbers are fake and don't exist on GitHub."""
    return (
        not task.get("demo")
        and task.get("status") == "completed"
        and bool(task.get("pr_url"))
        and bool(task.get("devin_session_id"))
    )


def _since(task: dict) -> str | None:
    """Only look at comments after Devin delivered the fix — earlier chatter
    (and Devin's own 'I'll be helping' bot note) is irrelevant."""
    return (
        task.get("pr_comments_synced_at")
        or task.get("end_time")
        or task.get("start_time")
    )


async def _all_pr_comments(pr_num: int, github) -> list:
    """Fetch all PR comments (no since filter) for bot-reply matching."""
    try:
        return await github.list_pr_comments(pr_num)
    except Exception:  # noqa: BLE001
        return []


async def forward_new_comments(
    task: dict, store: Store, github, devin
) -> int:
    """Forward not-yet-seen human PR comments for one task. Returns the
    number forwarded. Never raises."""
    pr_num = pr_number_from_url(task.get("pr_url"))
    if pr_num is None:
        return 0
    try:
        comments = await github.list_pr_comments(pr_num, since=_since(task))
    except Exception as e:  # noqa: BLE001
        log.warning("list_pr_comments failed for %s: %s",
                    task.get("internal_id"), e)
        return 0

    followups = task.setdefault("pr_followups", [])
    seen_ids = {f.get("comment_id") for f in followups}

    # Split into human comments and bot comments so we can match Devin's replies.
    all_comments = await _all_pr_comments(pr_num, github)
    bot_comments = [
        c for c in all_comments
        if (c.get("user_type") or "").lower() == "bot"
        and "devin" in (c.get("user_login") or "").lower()
    ]

    forwarded = 0
    for c in comments:
        cid = c.get("id")
        if cid in seen_ids:
            continue
        # Skip bots: Devin's own PR-helper bot, GitHub Actions, etc.
        if (c.get("user_type") or "").lower() == "bot":
            continue
        body = (c.get("body") or "").strip()
        if not body:
            continue
        user = c.get("user_login") or "a reviewer"
        relay = (
            f"New review comment on PR #{pr_num} from @{user} "
            f"(relayed by the issue-remediation orchestrator):\n\n"
            f"{body}\n\n"
            "Please address this in the same PR and push the changes."
        )
        try:
            await devin.send_message(task["devin_session_id"], relay)
        except Exception as e:  # noqa: BLE001
            log.warning("send_message failed for %s: %s",
                        task.get("internal_id"), e)
            continue  # retry this comment next cycle (not marked seen)

        # Find the first Devin bot reply that came after this human comment.
        devin_reply = None
        for bc in bot_comments:
            if (bc.get("created_at") or "") > (c.get("created_at") or ""):
                devin_reply = (bc.get("body") or "").strip() or None
                break

        followups.append(
            {
                "comment_id": cid,
                "user": user,
                "body": body,
                "created_at": c.get("created_at"),
                "forwarded_at": now_iso(),
                **({"devin_reply": devin_reply} if devin_reply else {}),
            }
        )
        seen_ids.add(cid)
        forwarded += 1
        log.info("Relayed PR #%s comment from @%s to session %s",
                 pr_num, user, task["devin_session_id"])

    # Backfill devin_reply on any existing followup that doesn't have one yet.
    for f in followups:
        if f.get("devin_reply"):
            continue
        for bc in bot_comments:
            if (bc.get("created_at") or "") > (f.get("created_at") or ""):
                reply = (bc.get("body") or "").strip()
                if reply:
                    f["devin_reply"] = reply
                break

    # Advance the window even when nothing matched, so we don't refetch the
    # whole comment history every cycle.
    task["pr_comments_synced_at"] = now_iso()
    store.save_task(task)
    return forwarded


async def refresh_pr_status(task: dict, store: Store, github) -> bool:
    """Refresh the merge state of a completed task's PR. Returns True if it
    changed (and was persisted). Lagging metric: a human may merge days
    later, so we keep re-checking completed tasks every cycle. Never raises."""
    pr_num = pr_number_from_url(task.get("pr_url"))
    if pr_num is None:
        return False
    try:
        status = await github.get_pr_status(pr_num)
    except Exception as e:  # noqa: BLE001
        log.warning("get_pr_status failed for %s: %s",
                    task.get("internal_id"), e)
        return False
    if not status:
        return False
    changed = (
        task.get("pr_state") != status["state"]
        or bool(task.get("pr_merged")) != status["merged"]
    )
    if not changed:
        return False
    task["pr_state"] = status["state"]
    task["pr_merged"] = status["merged"]
    task["pr_merged_at"] = status["merged_at"]
    store.save_task(task)
    if status["merged"]:
        log.info("PR for %s was merged by a human \U0001F389",
                 task.get("internal_id"))
    return True


async def watch_once(store: Store, github, devin) -> int:
    """One sweep over all eligible tasks: relay new PR comments AND refresh
    PR merge status. Returns total comments forwarded."""
    total = 0
    for task in store.load_all():
        if not _eligible(task):
            continue
        try:
            total += await forward_new_comments(task, store, github, devin)
            await refresh_pr_status(task, store, github)
        except Exception as e:  # noqa: BLE001
            log.warning("pr_watcher: task %s errored: %s",
                        task.get("internal_id"), e)
    return total


async def pr_comment_loop(
    stop_event, store: Store, github, devin, settings
) -> None:
    interval = getattr(settings, "pr_comment_poll_interval_seconds", 60)
    while not stop_event.is_set():
        try:
            await watch_once(store, github, devin)
        except Exception as e:  # noqa: BLE001
            log.warning("pr_comment cycle error: %s", e)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
