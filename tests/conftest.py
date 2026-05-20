"""Shared fixtures. No credentials / no network anywhere in the suite."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.devin_client import DevinClient
from app.store import Store


@pytest.fixture
def tmp_store(tmp_path) -> Store:
    return Store(tmp_path)


@pytest.fixture
def settings_ns() -> SimpleNamespace:
    # tiny intervals so the orchestrator poll loop is instant in tests
    return SimpleNamespace(
        issue_label="devin",
        devin_poll_interval_seconds=0,
        max_poll_minutes=60,
        poll_interval_seconds=0,
        pr_comment_poll_interval_seconds=0,
    )


class FakeGitHub:
    def __init__(self, issues=None, issue=None, pr_diff=None,
                 pr_comments=None, pr_status=None):
        self._issues = issues or []
        self._issue = issue
        self._pr_diff = pr_diff
        self._pr_comments = pr_comments or []
        self._pr_status = pr_status
        self.comments: list[tuple[int, str]] = []
        self.diff_calls: list[int] = []
        self.pr_comment_calls: list[tuple[int, str | None]] = []
        self.pr_status_calls: list[int] = []

    async def list_open_issues(self, label):
        return self._issues

    async def get_issue(self, number):
        return self._issue or {"number": number, "title": "t",
                               "html_url": f"https://x/issues/{number}"}

    async def get_pr_diff(self, pr_number):
        self.diff_calls.append(pr_number)
        return self._pr_diff

    async def list_pr_comments(self, pr_number, since=None):
        self.pr_comment_calls.append((pr_number, since))
        return self._pr_comments

    async def get_pr_status(self, pr_number):
        self.pr_status_calls.append(pr_number)
        return self._pr_status

    async def comment_on_issue(self, number, body):
        self.comments.append((number, body))


class FakeDevin:
    """Returns `create` then walks `sessions` on successive get_session calls."""

    def __init__(self, create, sessions, raise_on_create=False,
                 messages=None):
        self._create = create
        self._sessions = list(sessions)
        self._raise = raise_on_create
        self._messages = messages or []
        self.created = False
        self.sent: list[tuple[str, str]] = []

    async def create_session(self, **kwargs):
        if self._raise:
            raise RuntimeError("boom")
        self.created = True
        return self._create

    async def get_session(self, session_id):
        return self._sessions.pop(0) if len(self._sessions) > 1 \
            else self._sessions[0]

    async def get_messages(self, session_id, max_messages=40):
        return self._messages

    async def send_message(self, session_id, message):
        self.sent.append((session_id, message))
        return {}

    is_terminal = staticmethod(DevinClient.is_terminal)
    has_output = staticmethod(DevinClient.has_output)
    is_done = staticmethod(DevinClient.is_done)
    is_success = staticmethod(DevinClient.is_success)
    latest_devin_message = staticmethod(DevinClient.latest_devin_message)


@pytest.fixture
def fake_github_factory():
    return FakeGitHub


@pytest.fixture
def fake_devin_factory():
    return FakeDevin
