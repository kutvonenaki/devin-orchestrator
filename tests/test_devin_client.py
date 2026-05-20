import json

import httpx
import pytest

from app.devin_client import DevinAPIError, DevinClient

BASE = "https://api.devin.test/v3"
URL = f"{BASE}/organizations/org1/sessions"
MSGS = f"{URL}/s1/messages"


async def test_create_session_request(httpx_mock):
    httpx_mock.add_response(
        method="POST", url=URL,
        json={"session_id": "s1", "url": "u", "status": "running"},
    )
    c = DevinClient(BASE, "org1", "secret")
    out = await c.create_session(
        prompt="do it", structured_output_schema={"type": "object"},
        title="Fix", tags=["t"],
    )
    await c.aclose()

    assert out["session_id"] == "s1"
    req = httpx_mock.get_requests()[0]
    assert req.headers["authorization"] == "Bearer secret"
    body = json.loads(req.content)
    assert body["prompt"] == "do it"
    assert body["structured_output_schema"] == {"type": "object"}
    assert body["structured_output_required"] is True


async def test_create_session_idempotent_flag(httpx_mock):
    httpx_mock.add_response(
        method="POST", url=URL, json={"session_id": "s1"}
    )
    c = DevinClient(BASE, "org1", "k")
    await c.create_session(
        prompt="p", structured_output_schema={}, idempotent=True
    )
    await c.aclose()
    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body["idempotent"] is True


async def test_create_session_omits_idempotent_by_default(httpx_mock):
    httpx_mock.add_response(
        method="POST", url=URL, json={"session_id": "s1"}
    )
    c = DevinClient(BASE, "org1", "k")
    await c.create_session(prompt="p", structured_output_schema={})
    await c.aclose()
    body = json.loads(httpx_mock.get_requests()[0].content)
    assert "idempotent" not in body  # opt-in only


async def test_send_message_posts_body(httpx_mock):
    httpx_mock.add_response(
        method="POST", url=MSGS, json={"session_id": "s1"}
    )
    c = DevinClient(BASE, "org1", "k")
    out = await c.send_message("s1", "address the review comment")
    await c.aclose()
    assert out["session_id"] == "s1"
    req = httpx_mock.get_requests()[0]
    assert json.loads(req.content) == {
        "message": "address the review comment"
    }


async def test_send_message_tolerates_empty_body(httpx_mock):
    httpx_mock.add_response(method="POST", url=MSGS, status_code=204)
    c = DevinClient(BASE, "org1", "k")
    assert await c.send_message("s1", "go") == {}  # 204/empty -> {}
    await c.aclose()


async def test_get_session(httpx_mock):
    httpx_mock.add_response(
        method="GET", url=f"{URL}/s1",
        json={"session_id": "s1", "status": "exit"},
    )
    c = DevinClient(BASE, "org1", "k")
    s = await c.get_session("s1")
    await c.aclose()
    assert s["status"] == "exit"


async def test_4xx_raises_immediately_without_retry(httpx_mock):
    httpx_mock.add_response(method="POST", url=URL, status_code=404)
    c = DevinClient(BASE, "org1", "k", retry_backoff=0, max_retries=3)
    with pytest.raises(DevinAPIError):
        await c.create_session(prompt="p", structured_output_schema={})
    await c.aclose()
    assert len(httpx_mock.get_requests()) == 1  # no retry on 4xx


async def test_transient_5xx_is_retried_then_succeeds(httpx_mock):
    httpx_mock.add_response(method="POST", url=URL, status_code=502)
    httpx_mock.add_response(method="POST", url=URL, json={"session_id": "s1"})
    c = DevinClient(BASE, "org1", "k", retry_backoff=0, max_retries=3)
    out = await c.create_session(prompt="p", structured_output_schema={})
    await c.aclose()
    assert out["session_id"] == "s1"
    assert len(httpx_mock.get_requests()) == 2  # 1 failed + 1 success


async def test_persistent_5xx_raises_after_retries(httpx_mock):
    for _ in range(3):  # 1 initial + 2 retries
        httpx_mock.add_response(method="GET", url=f"{URL}/s1", status_code=500)
    c = DevinClient(BASE, "org1", "k", retry_backoff=0, max_retries=2)
    with pytest.raises(DevinAPIError):
        await c.get_session("s1")
    await c.aclose()
    assert len(httpx_mock.get_requests()) == 3


async def test_get_messages_paginates_and_merges(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(MSGS, params={"first": 100}),
        json={"items": [{"source": "user", "message": "a",
                         "created_at": 1}],
              "has_next_page": True, "end_cursor": "cur1"},
    )
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(MSGS, params={"first": 100, "after": "cur1"}),
        json={"items": [{"source": "devin", "message": "b",
                         "created_at": 2}],
              "has_next_page": False, "end_cursor": None},
    )
    c = DevinClient(BASE, "org1", "k")
    msgs = await c.get_messages("s1")
    await c.aclose()
    assert [m["message"] for m in msgs] == ["a", "b"]
    # second request carried the cursor forward
    assert "after=cur1" in str(httpx_mock.get_requests()[1].url)


async def test_get_messages_caps_and_truncates(httpx_mock):
    items = [
        {"source": "devin", "message": "x" * 5000, "created_at": i}
        for i in range(60)
    ]
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(MSGS, params={"first": 100}),
        json={"items": items, "has_next_page": False, "end_cursor": None},
    )
    c = DevinClient(BASE, "org1", "k")
    msgs = await c.get_messages("s1", max_messages=40)
    await c.aclose()
    assert len(msgs) == 40                       # capped to newest 40
    assert msgs[0]["created_at"] == 20           # oldest kept = item 20
    assert msgs[0]["message"].endswith("…[truncated]")
    assert len(msgs[0]["message"]) < 5000        # body truncated


async def test_get_messages_error_returns_empty(httpx_mock):
    for _ in range(2):  # 1 initial + 1 retry
        httpx_mock.add_response(
            method="GET",
            url=httpx.URL(MSGS, params={"first": 100}),
            status_code=500,
        )
    c = DevinClient(BASE, "org1", "k", retry_backoff=0, max_retries=1)
    assert await c.get_messages("s1") == []  # best-effort, never raises
    await c.aclose()


def test_latest_devin_message():
    msgs = [
        {"source": "user", "message": "do it"},
        {"source": "devin", "message": "first"},
        {"source": "devin", "message": "latest"},
        {"source": "user", "message": "ok thanks"},
    ]
    assert DevinClient.latest_devin_message(msgs) == "latest"
    assert DevinClient.latest_devin_message([]) is None
    assert DevinClient.latest_devin_message(
        [{"source": "user", "message": "only user"}]
    ) is None


def test_lifecycle_helpers():
    assert DevinClient.is_terminal("exit")
    assert DevinClient.is_terminal("error")
    assert not DevinClient.is_terminal("running")

    assert DevinClient.has_output({"structured_output": {"pr_url": "https://github.com/org/repo/pull/1"}})
    assert not DevinClient.has_output({"structured_output": {"pr_url": ""}})
    assert not DevinClient.has_output({"structured_output": None})

    # real Devin behavior: finished its deliverable but idles instead of exit
    idle = {"status": "running", "status_detail": "waiting_for_user",
            "structured_output": {"pr_url": "https://github.com/org/repo/pull/1"}}
    assert DevinClient.is_done(idle)
    assert DevinClient.is_success(idle)

    full_out = {"pr_url": "https://github.com/org/repo/pull/1"}
    # clean exit with full output -> success
    assert DevinClient.is_success({"status": "exit", "structured_output": full_out})
    # terminal but no output -> done, not success
    assert DevinClient.is_done({"status": "exit", "structured_output": None})
    assert not DevinClient.is_success({"status": "exit", "structured_output": None})
    # error wins even if some output is present
    assert not DevinClient.is_success({"status": "error", "structured_output": full_out})
    # still working, nothing produced -> keep polling
    assert not DevinClient.is_done({"status": "running", "structured_output": None})
