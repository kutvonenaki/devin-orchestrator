import asyncio

from tests.conftest import FakeDevin, FakeGitHub

from app.pr_watcher import (
    forward_new_comments,
    pr_comment_loop,
    refresh_pr_status,
    watch_once,
)


def _completed_task(**over):
    t = {
        "internal_id": "issue-1",
        "status": "completed",
        "pr_url": "https://github.com/o/r/pull/2",
        "devin_session_id": "sess-1",
        "end_time": "2026-05-19T18:00:00+00:00",
        "pr_followups": [],
        "pr_comments_synced_at": None,
    }
    t.update(over)
    return t


def _comment(cid, login="alice", utype="User", body="please also guard NaN"):
    return {
        "id": cid,
        "user_login": login,
        "user_type": utype,
        "body": body,
        "created_at": "2026-05-19T18:05:00Z",
    }


async def test_forwards_new_human_comment(tmp_store):
    task = _completed_task()
    tmp_store.save_task(task)
    gh = FakeGitHub(pr_comments=[_comment(11)])
    dv = FakeDevin(create={}, sessions=[{}])

    n = await forward_new_comments(task, tmp_store, gh, dv)

    assert n == 1
    # relayed into the Devin session, with the comment body embedded
    assert dv.sent and dv.sent[0][0] == "sess-1"
    assert "please also guard NaN" in dv.sent[0][1]
    # two calls: one with since (new comments), one without (bot-reply lookup)
    assert (2, "2026-05-19T18:00:00+00:00") in gh.pr_comment_calls
    assert (2, None) in gh.pr_comment_calls
    # persisted: recorded as a follow-up + high-water mark advanced
    saved = tmp_store.load_task("issue-1")
    assert [f["comment_id"] for f in saved["pr_followups"]] == [11]
    assert saved["pr_followups"][0]["user"] == "alice"
    assert saved["pr_comments_synced_at"] is not None


async def test_skips_bot_comments(tmp_store):
    task = _completed_task()
    tmp_store.save_task(task)
    gh = FakeGitHub(pr_comments=[_comment(12, login="devin", utype="Bot")])
    dv = FakeDevin(create={}, sessions=[{}])

    n = await forward_new_comments(task, tmp_store, gh, dv)

    assert n == 0
    assert dv.sent == []
    assert tmp_store.load_task("issue-1")["pr_followups"] == []


async def test_dedups_already_forwarded(tmp_store):
    task = _completed_task(
        pr_followups=[{"comment_id": 11, "user": "alice", "body": "x"}]
    )
    tmp_store.save_task(task)
    gh = FakeGitHub(pr_comments=[_comment(11)])
    dv = FakeDevin(create={}, sessions=[{}])

    n = await forward_new_comments(task, tmp_store, gh, dv)

    assert n == 0  # same comment id -> not relayed twice
    assert dv.sent == []


async def test_send_failure_not_marked_seen(tmp_store):
    class BoomDevin:
        async def send_message(self, sid, msg):
            raise RuntimeError("devin 502")

    task = _completed_task()
    tmp_store.save_task(task)
    gh = FakeGitHub(pr_comments=[_comment(11)])

    n = await forward_new_comments(task, tmp_store, gh, BoomDevin())

    assert n == 0
    # not recorded -> retried on the next cycle
    assert tmp_store.load_task("issue-1")["pr_followups"] == []


async def test_refresh_pr_status_persists_merge(tmp_store):
    task = _completed_task()
    tmp_store.save_task(task)
    gh = FakeGitHub(pr_status={"state": "closed", "merged": True,
                               "merged_at": "2026-05-20T10:00:00Z"})

    changed = await refresh_pr_status(task, tmp_store, gh)

    assert changed is True
    saved = tmp_store.load_task("issue-1")
    assert saved["pr_merged"] is True
    assert saved["pr_state"] == "closed"
    assert saved["pr_merged_at"] == "2026-05-20T10:00:00Z"


async def test_refresh_pr_status_noop_when_unchanged(tmp_store):
    task = _completed_task(pr_state="open", pr_merged=False)
    tmp_store.save_task(task)
    gh = FakeGitHub(pr_status={"state": "open", "merged": False,
                               "merged_at": None})

    changed = await refresh_pr_status(task, tmp_store, gh)

    assert changed is False  # nothing to persist -> no rewrite


async def test_watch_once_skips_ineligible(tmp_store):
    tmp_store.save_task(_completed_task(internal_id="issue-1"))  # eligible
    tmp_store.save_task(
        {"internal_id": "issue-2", "status": "running",
         "pr_url": "https://github.com/o/r/pull/3",
         "devin_session_id": "s2"}
    )  # not completed
    tmp_store.save_task(
        {"internal_id": "issue-3", "status": "completed",
         "pr_url": None, "devin_session_id": "s3"}
    )  # no PR
    gh = FakeGitHub(pr_comments=[_comment(11)])
    dv = FakeDevin(create={}, sessions=[{}])

    total = await watch_once(tmp_store, gh, dv)

    assert total == 1  # only issue-1 acted on
    # two calls per eligible task (since + bot-reply lookup), all for PR #2
    assert all(c[0] == 2 for c in gh.pr_comment_calls)


async def test_loop_swallows_errors(tmp_store, settings_ns):
    class Boom:
        async def list_pr_comments(self, *a, **k):
            raise RuntimeError("github down")

    tmp_store.save_task(_completed_task())
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.02)
        stop.set()

    # must not raise even though list_pr_comments always errors
    await asyncio.gather(
        pr_comment_loop(stop, tmp_store, Boom(),
                        FakeDevin(create={}, sessions=[{}]), settings_ns),
        stopper(),
    )
