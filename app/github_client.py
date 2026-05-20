"""Async GitHub Issues client. Token is OPTIONAL.

No token -> unauthenticated reads (fine for a public fork) and
comment_on_issue becomes a logged no-op.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

_PR_URL_RE = re.compile(r"/pull/(\d+)")


def pr_number_from_url(pr_url: Optional[str]) -> Optional[int]:
    """Extract the PR number from a GitHub PR URL (…/pull/<n>)."""
    if not pr_url:
        return None
    m = _PR_URL_RE.search(pr_url)
    return int(m.group(1)) if m else None


class GitHubClient:
    def __init__(
        self, repo: str, token: Optional[str] = None, timeout: float = 30.0
    ):
        owner, _, name = repo.partition("/")
        self._owner, self._repo = owner, name
        self._has_token = bool(token)
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(
            base_url="https://api.github.com", headers=headers, timeout=timeout
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_open_issues(self, label: str) -> list[dict[str, Any]]:
        r = await self._client.get(
            f"/repos/{self._owner}/{self._repo}/issues",
            params={"state": "open", "labels": label},
        )
        r.raise_for_status()
        # GitHub returns PRs in the issues feed; drop them.
        return [i for i in r.json() if "pull_request" not in i]

    async def get_issue(self, number: int) -> dict[str, Any]:
        r = await self._client.get(
            f"/repos/{self._owner}/{self._repo}/issues/{number}"
        )
        r.raise_for_status()
        return r.json()

    async def get_pr_diff(self, pr_number: int) -> Optional[str]:
        """Fetch the authoritative unified diff for a PR.

        Returns None on any failure — the diff is a nice-to-have for the
        dashboard, never worth failing a completed task over.
        """
        try:
            r = await self._client.get(
                f"/repos/{self._owner}/{self._repo}/pulls/{pr_number}",
                headers={"Accept": "application/vnd.github.v3.diff"},
            )
            r.raise_for_status()
            return r.text
        except httpx.HTTPError as e:
            log.warning("get_pr_diff(#%s) failed: %s", pr_number, e)
            return None

    async def get_pr_status(
        self, pr_number: int
    ) -> Optional[dict[str, Any]]:
        """Return {state, merged, merged_at} for a PR, or None on failure.

        This is how we measure the *human-validated* outcome: ``merged`` is
        True only once a person actually merged Devin's PR. Best-effort —
        merge tracking is a lagging metric, never worth raising over.
        """
        try:
            r = await self._client.get(
                f"/repos/{self._owner}/{self._repo}/pulls/{pr_number}"
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("get_pr_status(#%s) failed: %s", pr_number, e)
            return None
        d = r.json()
        return {
            "state": d.get("state"),          # "open" | "closed"
            "merged": bool(d.get("merged")),  # True only if actually merged
            "merged_at": d.get("merged_at"),  # ISO ts or None
        }

    async def list_pr_comments(
        self, pr_number: int, since: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """List conversation comments on a PR (PRs are issues for the
        comments API), newest activity last.

        ``since`` is an ISO-8601 timestamp; GitHub returns only comments
        updated at/after it. Best-effort: any failure yields [] — a flaky
        comment fetch must never crash the watcher loop.
        """
        try:
            params: dict[str, Any] = {"per_page": 100}
            if since:
                params["since"] = since
            r = await self._client.get(
                f"/repos/{self._owner}/{self._repo}/issues/"
                f"{pr_number}/comments",
                params=params,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("list_pr_comments(#%s) failed: %s", pr_number, e)
            return []
        out: list[dict[str, Any]] = []
        for c in r.json():
            user = c.get("user") or {}
            out.append(
                {
                    "id": c.get("id"),
                    "user_login": user.get("login"),
                    "user_type": user.get("type"),  # "User" | "Bot"
                    "body": c.get("body") or "",
                    "created_at": c.get("created_at"),
                }
            )
        return out

    async def comment_on_issue(self, number: int, body: str) -> None:
        if not self._has_token:
            log.info(
                "No GITHUB_TOKEN; skipping comment on issue #%s", number
            )
            return
        r = await self._client.post(
            f"/repos/{self._owner}/{self._repo}/issues/{number}/comments",
            json={"body": body},
        )
        r.raise_for_status()
