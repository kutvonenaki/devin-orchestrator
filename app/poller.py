"""Scheduled GitHub-issue poller.

One asyncio loop (started in the FastAPI lifespan). Every poll cycle lists
open labelled issues, skips ones already in the store (dedup), and launches
the orchestrator for each new one (bounded concurrency). Transient API errors
do not kill the loop.
"""

from __future__ import annotations

import asyncio
import logging

from . import orchestrator

log = logging.getLogger(__name__)


async def poll_once(
    store,
    github,
    devin,
    settings,
    semaphore: asyncio.Semaphore,
    backlog: list | None = None,
) -> list[asyncio.Task]:
    issues = await github.list_open_issues(settings.issue_label)
    if backlog is not None:
        # pending = open labelled issues not yet taken into the store
        backlog[:] = [
            {
                "number": i["number"],
                "title": i.get("title"),
                "html_url": i.get("html_url"),
            }
            for i in issues
            if not store.exists(f"issue-{i['number']}")
        ]
    created: list[asyncio.Task] = []
    for issue in issues:
        internal_id = f"issue-{issue['number']}"
        if store.exists(internal_id):
            continue

        async def _run(iss=issue):
            async with semaphore:
                await orchestrator.process_issue(
                    iss, store, devin, github, settings
                )

        created.append(asyncio.create_task(_run()))
    if created:
        log.info("Poller launched %d new issue(s)", len(created))
    return created


async def poll_loop(
    stop_event, store, github, devin, settings, backlog: list | None = None
) -> None:
    semaphore = asyncio.Semaphore(3)
    while not stop_event.is_set():
        try:
            await poll_once(
                store, github, devin, settings, semaphore, backlog
            )
        except Exception as e:  # noqa: BLE001
            log.warning("poll cycle error: %s", e)
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=settings.poll_interval_seconds
            )
        except asyncio.TimeoutError:
            pass
