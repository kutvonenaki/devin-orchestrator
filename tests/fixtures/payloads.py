"""Canned payloads for tests (no network)."""

from __future__ import annotations

from typing import Any


def issue(number: int = 5, title: str = "Chart breaks") -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "html_url": f"https://github.com/o/r/issues/{number}",
    }


def issue_list_with_pr() -> list[dict[str, Any]]:
    return [
        issue(1, "real issue one"),
        issue(2, "real issue two"),
        {  # a PR shows up in the issues feed and must be filtered out
            "number": 99,
            "title": "a pull request",
            "html_url": "https://github.com/o/r/pull/99",
            "pull_request": {"url": "https://api.github.com/.../pulls/99"},
        },
    ]


def session_running() -> dict[str, Any]:
    return {"session_id": "sess-1", "url": "https://app.devin.ai/sessions/1",
            "status": "running"}


def structured_output() -> dict[str, Any]:
    return {
        "pr_url": "https://github.com/o/r/pull/123",
        "root_cause_analysis": "compare.py divides by c_df without a guard.",
        "resolution_summary": "Guard zero denominator; return NaN.",
        "files_edited": ["superset/utils/pandas_postprocessing/compare.py"],
        "file_changes": [
            {"path": "superset/utils/pandas_postprocessing/compare.py",
             "change_summary": "Guarded division by zero."}
        ],
        "test_command_run": "pytest tests/.../test_compare_zero.py",
        "test_stdout": "1 passed in 0.12s",
    }


def worklog() -> list[dict[str, Any]]:
    return [
        {"source": "user", "message": "Fix the bug", "created_at": 1779208687},
        {"source": "devin", "message": "Investigating compare.py",
         "created_at": 1779208700},
        {"source": "devin", "message": "Opened PR with the fix",
         "created_at": 1779208900},
    ]


def session_completed() -> dict[str, Any]:
    return {
        "session_id": "sess-1",
        "status": "exit",
        "status_detail": "finished",
        "structured_output": structured_output(),
        "pull_requests": [{"url": "https://github.com/o/r/pull/123"}],
        "acus_consumed": 3.5,
    }


def session_failed() -> dict[str, Any]:
    return {"session_id": "sess-1", "status": "exit",
            "status_detail": "finished", "structured_output": None}
