from tests.conftest import FakeDevin, FakeGitHub
from tests.fixtures import payloads

from app.orchestrator import process_issue


async def test_success_flow(tmp_store, settings_ns):
    devin = FakeDevin(
        create=payloads.session_running(),
        sessions=[payloads.session_completed()],
        messages=payloads.worklog(),
    )
    gh = FakeGitHub(pr_diff="--- a/compare.py\n+++ b/compare.py\n@@ guard")
    await process_issue(payloads.issue(5), tmp_store, devin, gh, settings_ns)

    task = tmp_store.load_task("issue-5")
    assert task["status"] == "completed"
    assert task["pr_url"] == "https://github.com/o/r/pull/123"
    assert task["structured_output"]["files_edited"]
    assert task["end_time"]
    assert gh.comments and "pull/123" in gh.comments[0][1]
    # diff comes from the PR on GitHub, not structured_output
    assert "guard" in task["code_diff"]
    assert gh.diff_calls == [123]
    assert "code_diff" not in task["structured_output"]
    # worklog + cost persisted for the dashboard
    assert task["worklog"] == payloads.worklog()
    assert task["acus_consumed"] == 3.5


async def test_live_message_updated_while_running(tmp_store, settings_ns):
    # first poll sees a still-running session (triggers _refresh_progress),
    # second poll sees it completed
    running = {"session_id": "sess-1", "status": "running",
               "structured_output": None, "acus_consumed": 1.2}
    devin = FakeDevin(
        create=payloads.session_running(),
        sessions=[running, payloads.session_completed()],
        messages=payloads.worklog(),
    )
    await process_issue(payloads.issue(9), tmp_store, devin,
                        FakeGitHub(pr_diff="d"), settings_ns)
    t = tmp_store.load_task("issue-9")
    assert t["status"] == "completed"
    # latest non-user message surfaced during the running cycle
    assert t["latest_message"] == "Opened PR with the fix"


async def test_completed_when_idle_with_output(tmp_store, settings_ns):
    # Devin produced structured_output but idles at waiting_for_user (real
    # behavior) — must still be treated as completed, not timed-out/failed.
    idle = {
        "session_id": "sess-1",
        "status": "running",
        "status_detail": "waiting_for_user",
        "structured_output": payloads.structured_output(),
        "pull_requests": [{"url": "https://github.com/o/r/pull/123"}],
    }
    devin = FakeDevin(create=payloads.session_running(), sessions=[idle])
    await process_issue(payloads.issue(11), tmp_store, devin, FakeGitHub(),
                        settings_ns)
    t = tmp_store.load_task("issue-11")
    assert t["status"] == "completed"
    assert t["pr_url"] == "https://github.com/o/r/pull/123"


async def test_failure_when_no_structured_output(tmp_store, settings_ns):
    devin = FakeDevin(
        create=payloads.session_running(),
        sessions=[payloads.session_failed()],
    )
    await process_issue(payloads.issue(6), tmp_store, devin, FakeGitHub(),
                        settings_ns)
    task = tmp_store.load_task("issue-6")
    assert task["status"] == "failed"
    assert task["error"]


async def test_exception_marks_failed_and_no_crash(tmp_store, settings_ns):
    devin = FakeDevin(create={}, sessions=[{}], raise_on_create=True)
    await process_issue(payloads.issue(7), tmp_store, devin, FakeGitHub(),
                        settings_ns)
    task = tmp_store.load_task("issue-7")
    assert task["status"] == "failed"
    assert "boom" in task["error"]


async def test_dedup_skips_existing(tmp_store, settings_ns):
    tmp_store.save_task({"internal_id": "issue-8", "status": "completed"})
    # raise_on_create would blow up if create_session were called
    devin = FakeDevin(create={}, sessions=[{}], raise_on_create=True)
    await process_issue(payloads.issue(8), tmp_store, devin, FakeGitHub(),
                        settings_ns)
    assert tmp_store.load_task("issue-8")["status"] == "completed"
    assert devin.created is False
