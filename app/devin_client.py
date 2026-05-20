"""Async client for the Devin v3 API.

Base: {DEVIN_API_BASE}/organizations/{org_id}/sessions
Auth: Authorization: Bearer {DEVIN_API_KEY}

Resilient to transient failures: 5xx responses and transport/timeout errors
are retried with linear backoff (real long-poll loops WILL hit occasional
502s). 4xx are raised immediately (real errors: bad auth, not found).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

TERMINAL_STATUSES = {"exit", "error"}

# Worklog persistence caps (keep the JSON store small, dashboard snappy).
DEFAULT_MAX_MESSAGES = 40
MAX_MESSAGE_CHARS = 2048


class DevinAPIError(RuntimeError):
    pass


class DevinClient:
    def __init__(
        self,
        base: str,
        org_id: str,
        api_key: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
    ):
        self._base = base.rstrip("/")
        self._org = org_id
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def _sessions_url(self) -> str:
        return f"{self._base}/organizations/{self._org}/sessions"

    async def _request(self, method: str, url: str, **kw) -> httpx.Response:
        attempt = 0
        while True:
            try:
                r = await self._client.request(method, url, **kw)
                r.raise_for_status()
                return r
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status >= 500 and attempt < self._max_retries:
                    attempt += 1
                    log.warning(
                        "Devin %s %s -> HTTP %s; retry %d/%d",
                        method, url, status, attempt, self._max_retries,
                    )
                    await asyncio.sleep(self._retry_backoff * attempt)
                    continue
                raise DevinAPIError(f"{method} {url} failed: {e}") from e
            except httpx.HTTPError as e:  # transport / timeout / connect
                if attempt < self._max_retries:
                    attempt += 1
                    log.warning(
                        "Devin %s %s transport error (%s); retry %d/%d",
                        method, url, e, attempt, self._max_retries,
                    )
                    await asyncio.sleep(self._retry_backoff * attempt)
                    continue
                raise DevinAPIError(f"{method} {url} failed: {e}") from e

    async def create_session(
        self,
        prompt: str,
        structured_output_schema: dict,
        title: Optional[str] = None,
        tags: Optional[list[str]] = None,
        repos: Optional[list[str]] = None,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "prompt": prompt,
            "structured_output_schema": structured_output_schema,
            "structured_output_required": True,
        }
        if title:
            body["title"] = title
        if tags:
            body["tags"] = tags
        if repos:
            body["repos"] = repos
        if idempotent:
            # Devin dedups on the (deterministic) prompt: a re-issued create
            # for the same issue returns the existing session instead of
            # spawning a duplicate. Prevents the orphaned-duplicate scenario
            # when the orchestrator restarts mid-flight.
            body["idempotent"] = True
        r = await self._request("POST", self._sessions_url, json=body)
        return r.json()

    async def get_session(self, session_id: str) -> dict[str, Any]:
        r = await self._request("GET", f"{self._sessions_url}/{session_id}")
        return r.json()

    async def send_message(
        self, session_id: str, message: str
    ) -> dict[str, Any]:
        """Send a follow-up message into an existing session.

        Wakes a session idling at ``waiting_for_user`` so it acts on the
        instruction (used to forward GitHub PR comments back to Devin).
        """
        r = await self._request(
            "POST",
            f"{self._sessions_url}/{session_id}/messages",
            json={"message": message},
        )
        try:
            return r.json()
        except ValueError:
            return {}  # some deployments return 204/empty on accept

    async def get_messages(
        self,
        session_id: str,
        max_messages: int = DEFAULT_MAX_MESSAGES,
    ) -> list[dict[str, Any]]:
        """Fetch the session worklog (oldest-first), capped to the newest
        `max_messages`, each message body truncated to MAX_MESSAGE_CHARS.

        Best-effort: any API error yields [] (the worklog is observability,
        never worth failing a task over).
        """
        url = f"{self._sessions_url}/{session_id}/messages"
        items: list[dict[str, Any]] = []
        cursor: Optional[str] = None
        try:
            # Hard page cap so a runaway session can't loop us forever.
            for _ in range(50):
                params: dict[str, Any] = {"first": 100}
                if cursor:
                    params["after"] = cursor
                r = await self._request("GET", url, params=params)
                data = r.json()
                items.extend(data.get("items") or [])
                if not data.get("has_next_page"):
                    break
                cursor = data.get("end_cursor")
                if not cursor:
                    break
        except DevinAPIError as e:
            log.warning("get_messages(%s) failed: %s", session_id, e)
            return []

        trimmed = items[-max_messages:]
        out: list[dict[str, Any]] = []
        for m in trimmed:
            msg = m.get("message") or ""
            if len(msg) > MAX_MESSAGE_CHARS:
                msg = msg[:MAX_MESSAGE_CHARS] + " …[truncated]"
            out.append(
                {
                    "source": m.get("source"),
                    "message": msg,
                    "created_at": m.get("created_at"),
                }
            )
        return out

    @staticmethod
    def latest_devin_message(messages: list[dict[str, Any]]) -> Optional[str]:
        """The most recent non-user message (Devin's current activity)."""
        for m in reversed(messages):
            if m.get("source") and m["source"] != "user" and m.get("message"):
                return m["message"]
        return None

    @staticmethod
    def is_terminal(status: Optional[str]) -> bool:
        return status in TERMINAL_STATUSES

    @staticmethod
    def has_output(session: dict[str, Any]) -> bool:
        out = session.get("structured_output") or {}
        # Require pr_url to be non-empty — partial output (e.g. only
        # root_cause filled in) must not be mistaken for a finished run.
        return bool(out.get("pr_url"))

    @staticmethod
    def is_done(session: dict[str, Any]) -> bool:
        """Stop polling: hard-terminal, OR Devin produced the required
        structured output (it often then idles at waiting_for_user instead
        of reaching status=exit)."""
        return (
            DevinClient.is_terminal(session.get("status"))
            or DevinClient.has_output(session)
        )

    @staticmethod
    def is_success(session: dict[str, Any]) -> bool:
        if session.get("status") == "error" or (
            session.get("status_detail") == "error"
        ):
            return False
        # structured_output_required=True -> its presence means the
        # deliverable is complete, regardless of exit vs. idle.
        return DevinClient.has_output(session)
