import json

import httpx

from app.github_client import GitHubClient, pr_number_from_url
from tests.fixtures import payloads


def test_pr_number_from_url():
    assert pr_number_from_url("https://github.com/o/r/pull/123") == 123
    assert pr_number_from_url("https://github.com/o/r/pull/7/files") == 7
    assert pr_number_from_url(None) is None
    assert pr_number_from_url("https://github.com/o/r/issues/5") is None


async def test_get_pr_diff_uses_diff_media_type(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/o/r/pulls/123",
        text="--- a/x\n+++ b/x\n@@ -1 +1 @@",
    )
    c = GitHubClient("o/r", token="tok")
    diff = await c.get_pr_diff(123)
    await c.aclose()
    assert "+++ b/x" in diff
    req = httpx_mock.get_requests()[0]
    assert req.headers["accept"] == "application/vnd.github.v3.diff"


async def test_get_pr_diff_returns_none_on_error(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/o/r/pulls/404",
        status_code=404,
    )
    c = GitHubClient("o/r", token=None)
    assert await c.get_pr_diff(404) is None  # best-effort, never raises
    await c.aclose()


async def test_list_open_issues_filters_prs(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.github.com/repos/o/r/issues",
            params={"state": "open", "labels": "devin"},
        ),
        json=payloads.issue_list_with_pr(),
    )
    c = GitHubClient("o/r", token=None)
    issues = await c.list_open_issues("devin")
    await c.aclose()
    nums = sorted(i["number"] for i in issues)
    assert nums == [1, 2]  # PR #99 filtered out


async def test_get_issue(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/o/r/issues/5",
        json=payloads.issue(5),
    )
    c = GitHubClient("o/r", token="tok")
    issue = await c.get_issue(5)
    await c.aclose()
    assert issue["number"] == 5


async def test_list_pr_comments_normalizes_and_passes_since(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.github.com/repos/o/r/issues/2/comments",
            params={"per_page": 100, "since": "2026-05-19T18:00:00+00:00"},
        ),
        json=[
            {
                "id": 11,
                "user": {"login": "alice", "type": "User"},
                "body": "also guard NaN",
                "created_at": "2026-05-19T18:05:00Z",
            },
            {
                "id": 12,
                "user": {"login": "devin-ai", "type": "Bot"},
                "body": "on it",
                "created_at": "2026-05-19T18:06:00Z",
            },
        ],
    )
    c = GitHubClient("o/r", token=None)
    out = await c.list_pr_comments(2, since="2026-05-19T18:00:00+00:00")
    await c.aclose()
    assert [(x["id"], x["user_login"], x["user_type"]) for x in out] == [
        (11, "alice", "User"),
        (12, "devin-ai", "Bot"),
    ]


async def test_get_pr_status_parses_merge_state(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/o/r/pulls/7",
        json={"state": "closed", "merged": True,
              "merged_at": "2026-05-20T10:00:00Z"},
    )
    c = GitHubClient("o/r", token=None)
    st = await c.get_pr_status(7)
    await c.aclose()
    assert st == {"state": "closed", "merged": True,
                  "merged_at": "2026-05-20T10:00:00Z"}


async def test_get_pr_status_none_on_error(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/o/r/pulls/9",
        status_code=500,
    )
    c = GitHubClient("o/r", token=None)
    assert await c.get_pr_status(9) is None  # best-effort
    await c.aclose()


async def test_list_pr_comments_returns_empty_on_error(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.github.com/repos/o/r/issues/9/comments",
            params={"per_page": 100},
        ),
        status_code=500,
    )
    c = GitHubClient("o/r", token=None)
    assert await c.list_pr_comments(9) == []  # best-effort, never raises
    await c.aclose()


async def test_comment_with_token_posts(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.github.com/repos/o/r/issues/5/comments",
        json={"id": 1},
        status_code=201,
    )
    c = GitHubClient("o/r", token="tok")
    await c.comment_on_issue(5, "hello")
    await c.aclose()
    req = httpx_mock.get_requests()[0]
    assert json.loads(req.content) == {"body": "hello"}
    assert req.headers["authorization"] == "Bearer tok"


async def test_comment_without_token_is_noop(httpx_mock):
    c = GitHubClient("o/r", token=None)
    await c.comment_on_issue(5, "hello")  # must not raise / not call API
    await c.aclose()
    assert httpx_mock.get_requests() == []
