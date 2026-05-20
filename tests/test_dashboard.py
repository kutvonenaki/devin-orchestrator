from fastapi.testclient import TestClient

from app import orchestrator as orchestrator_mod
from app.main import app as fastapi_app
from app.store import Store
from tests.conftest import FakeGitHub


def _seed(tmp_path):
    s = Store(tmp_path)
    s.save_task({
        "internal_id": "issue-5", "issue_number": 5,
        "issue_title": "Chart breaks", "status": "completed",
        "start_time": "2026-01-01T00:00:00+00:00",
        "end_time": "2026-01-01T00:01:00+00:00",
        "pr_url": "https://github.com/o/r/pull/1",
        "code_diff": "@@ -1 +1 @@ DIFFMARKER",
        "acus_consumed": 2.5,
        "worklog": [
            {"source": "user", "message": "fix it", "created_at": 1779208687},
            {"source": "devin", "message": "WORKLOGMARKER done",
             "created_at": 1779208900},
        ],
        "structured_output": {
            "root_cause_analysis": "div by zero",
            "resolution_summary": "guarded",
            "file_changes": [{"path": "compare.py", "change_summary": "guard"}],
            "test_command_run": "pytest x",
            "test_stdout": "1 passed",
        },
    })
    s.save_task({
        "internal_id": "issue-6", "issue_number": 6,
        "issue_title": "Other chart", "status": "running",
        "start_time": "2026-01-01T00:02:00+00:00",
        "latest_message": "LIVEMARKER investigating compare.py",
    })


def test_healthz_and_dashboard_and_api(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_DISABLE_POLLER", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed(tmp_path)

    with TestClient(fastapi_app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}

        page = client.get("/")
        assert page.status_code == 200
        assert "Avg MTTR" in page.text
        assert "Chart breaks" in page.text
        assert "1 passed" in page.text          # structured_output rendered
        assert "ACUs Spent" in page.text        # cost card present
        assert "DIFFMARKER" in page.text        # PR diff rendered
        assert "WORKLOGMARKER" in page.text     # worklog timeline rendered
        assert "LIVEMARKER" in page.text        # running row live message

        data = client.get("/api/tasks").json()
        assert data["metrics"]["completed"] == 1
        assert data["metrics"]["total_acus"] == 2.5
        assert {t["internal_id"] for t in data["tasks"]} == {
            "issue-5", "issue-6"
        }


def test_trigger_503_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_DISABLE_POLLER", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(fastapi_app) as client:
        r = client.post("/trigger", json={"issue_number": 5})
        assert r.status_code == 503


def test_trigger_202_with_injected_clients(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_DISABLE_POLLER", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    called = []

    async def fake_process(issue, store, devin, github, settings):
        called.append(issue["number"])

    monkeypatch.setattr(orchestrator_mod, "process_issue", fake_process)

    with TestClient(fastapi_app) as client:
        fastapi_app.state.github = FakeGitHub(
            issue={"number": 5, "title": "t",
                   "html_url": "https://x/issues/5"}
        )
        fastapi_app.state.devin = object()
        fastapi_app.state.settings = object()
        r = client.post("/trigger", json={"issue_number": 5})
        assert r.status_code == 202
        assert r.json() == {"internal_id": "issue-5"}
