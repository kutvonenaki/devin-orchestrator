"""FastAPI app: lifespan-managed poller + /trigger + /healthz + dashboard.

The dashboard/store work with no credentials. The poller only starts when
valid Devin settings exist and ORCH_DISABLE_POLLER != "1" (tests set it so
the suite never touches real APIs).
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import orchestrator
from .dashboard import render_dashboard
from .store import Store

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class TriggerRequest(BaseModel):
    issue_number: int


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.store = Store(os.getenv("DATA_DIR", "./data"))
    app.state.settings = None
    app.state.devin = None
    app.state.github = None
    app.state.backlog = []  # pending labelled issues, published by the poller
    app.state.stop_event = asyncio.Event()
    app.state.poller_task = None
    app.state.pr_watcher_task = None

    if os.getenv("ORCH_DISABLE_POLLER") == "1":
        log.info("Poller disabled via ORCH_DISABLE_POLLER")
    else:
        try:
            from .config import get_settings
            from .devin_client import DevinClient
            from .github_client import GitHubClient
            from .poller import poll_loop
            from .pr_watcher import pr_comment_loop

            s = get_settings()
            app.state.settings = s
            app.state.store = Store(s.data_dir)
            app.state.devin = DevinClient(
                s.devin_api_base, s.devin_org_id, s.devin_api_key
            )
            app.state.github = GitHubClient(s.github_repo, s.github_token)
            app.state.poller_task = asyncio.create_task(
                poll_loop(
                    app.state.stop_event,
                    app.state.store,
                    app.state.github,
                    app.state.devin,
                    s,
                    app.state.backlog,
                )
            )
            app.state.pr_watcher_task = asyncio.create_task(
                pr_comment_loop(
                    app.state.stop_event,
                    app.state.store,
                    app.state.github,
                    app.state.devin,
                    s,
                )
            )

            # Re-attach to any sessions that were in-flight before a restart
            in_flight = [
                t for t in app.state.store.load_all()
                if t.get("status") in ("running", "initializing")
                and t.get("devin_session_id")
            ]
            for t in in_flight:
                asyncio.create_task(
                    orchestrator.resume_session(
                        t, app.state.store, app.state.devin,
                        app.state.github, s,
                    )
                )
            if in_flight:
                log.info("Resumed %d in-flight session(s)", len(in_flight))

            log.info(
                "Poller started (label=%s, every %ss); "
                "PR-comment watcher every %ss",
                s.issue_label,
                s.poll_interval_seconds,
                s.pr_comment_poll_interval_seconds,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("Poller disabled (no/invalid credentials): %s", e)

    try:
        yield
    finally:
        app.state.stop_event.set()
        for t in (app.state.poller_task, app.state.pr_watcher_task):
            if t:
                t.cancel()
        for client in (app.state.devin, app.state.github):
            aclose = getattr(client, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception as e:  # noqa: BLE001
                    log.warning("client close failed: %s", e)


app = FastAPI(
    title="Devin Issue-Remediation Orchestrator", lifespan=lifespan
)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/api/tasks")
async def api_tasks():
    store = app.state.store
    tasks = store.load_all()
    return {
        "metrics": store.metrics(tasks),
        "tasks": tasks,
        "backlog": app.state.backlog,
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    store = app.state.store
    tasks = store.load_all()
    return render_dashboard(store.metrics(tasks), tasks, app.state.backlog)


@app.post("/trigger", status_code=202)
async def trigger(req: TriggerRequest):
    github = app.state.github
    if github is None:
        return JSONResponse(
            status_code=503,
            content={"detail": "credentials/poller not configured"},
        )
    issue = await github.get_issue(req.issue_number)
    asyncio.create_task(
        orchestrator.process_issue(
            issue,
            app.state.store,
            app.state.devin,
            github,
            app.state.settings,
        )
    )
    return {"internal_id": f"issue-{req.issue_number}"}
