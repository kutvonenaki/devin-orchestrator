import asyncio

from tests.conftest import FakeGitHub
from tests.fixtures import payloads

import app.orchestrator
from app.poller import poll_loop, poll_once


async def test_poll_once_dedups_and_launches_new(tmp_store, settings_ns,
                                                 monkeypatch):
    seen = []

    async def recorder(issue, store, devin, github, settings):
        seen.append(issue["number"])

    monkeypatch.setattr(app.orchestrator, "process_issue", recorder)

    # issue-1 already processed; issues 1 & 2 are open
    tmp_store.save_task({"internal_id": "issue-1", "status": "completed"})
    gh = FakeGitHub(issues=[payloads.issue(1), payloads.issue(2)])

    backlog: list = []
    tasks = await poll_once(tmp_store, gh, object(), settings_ns,
                            asyncio.Semaphore(3), backlog)
    # backlog reflects pending (not-yet-in-store) issues before they start
    assert [b["number"] for b in backlog] == [2]
    await asyncio.gather(*tasks)

    assert seen == [2]  # only the new one


async def test_poll_loop_swallows_errors(tmp_store, settings_ns):
    class Boom:
        async def list_open_issues(self, label):
            raise RuntimeError("github down")

    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.02)
        stop.set()

    # must not raise even though list_open_issues always errors
    await asyncio.gather(
        poll_loop(stop, tmp_store, Boom(), object(), settings_ns),
        stopper(),
    )
