"""Seed (or clear) fabricated demo tasks for a populated dashboard.

These rows are **counted in the metric cards** (Success Rate, PRs Merged,
MTTR, ACUs) so a presentation dashboard looks realistic — but every seeded
file carries ``"demo": true`` so:

  * the dashboard shows an honest "sample data" disclosure, and
  * ``--clear`` removes ONLY these, never a real run.

No credentials needed (writes JSON straight to the store).

    python scripts/seed_demo_data.py            # seed
    python scripts/seed_demo_data.py --clear     # remove only demo rows
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.store import Store  # noqa: E402

REPO = os.getenv("GITHUB_REPO", "kutvonenaki/superset")
_NOW = datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _completed(
    num: int,
    title: str,
    *,
    hours_ago: float,
    duration_min: float,
    acus: float,
    root: str,
    resolution: str,
    files: list[tuple[str, str]],
    diff: str,
    pr_merged: bool,
    pr_state: str,
) -> dict:
    start = _NOW - timedelta(hours=hours_ago)
    end = start + timedelta(minutes=duration_min)
    sid = f"demo{num}"
    return {
        "demo": True,
        "internal_id": f"issue-{num}",
        "issue_number": num,
        "issue_url": f"https://github.com/{REPO}/issues/{num}",
        "issue_title": title,
        "issue_created_at": _iso(start - timedelta(days=2, hours=5)),
        "status": "completed",
        "devin_session_id": sid,
        "devin_session_url": f"https://app.devin.ai/sessions/{sid}",
        "start_time": _iso(start),
        "end_time": _iso(end),
        "pr_url": f"https://github.com/{REPO}/pull/{num}",
        "structured_output": {
            "pr_url": f"https://github.com/{REPO}/pull/{num}",
            "root_cause_analysis": root,
            "resolution_summary": resolution,
            "files_edited": [f for f, _ in files],
            "file_changes": [
                {"path": f, "change_summary": s} for f, s in files
            ],
            "test_command_run": (
                "python -m pytest tests/unit_tests -q --noconftest"
            ),
            "test_stdout": (
                "============================= test session starts "
                "=============================\n"
                "collected 1 item\n\n"
                "tests/unit_tests/...::test_demo PASSED                  "
                "[100%]\n\n"
                "============================== 1 passed in 0.9s "
                "==============================="
            ),
        },
        "code_diff": diff,
        "worklog": [
            {
                "source": "user",
                "message": f"Investigate and fix issue #{num}: {title}",
                "created_at": int(start.timestamp()),
            },
            {
                "source": "devin",
                "message": (
                    f"Reproduced the issue, identified the root cause "
                    f"and opened a PR. {resolution}"
                ),
                "created_at": int(end.timestamp()),
            },
        ],
        "latest_message": None,
        "acus_consumed": acus,
        "pr_followups": [],
        "pr_comments_synced_at": None,
        "pr_state": pr_state,
        "pr_merged": pr_merged,
        "pr_merged_at": _iso(end + timedelta(hours=2)) if pr_merged else None,
        "error": None,
    }


def _demo_tasks() -> list[dict]:
    tasks = [
        _completed(
            9001,
            "Numeric range filter excludes rows exactly on the boundary",
            hours_ago=40, duration_min=14, acus=4.1,
            root="`utils/filters.py` used strict `<`/`>` instead of "
                 "inclusive bounds for numeric range filters.",
            resolution="Switched the numeric range filter to inclusive "
                       "comparisons so boundary values are retained.",
            files=[("superset/utils/filters.py",
                    "Use >= / <= for numeric range bounds.")],
            diff="--- a/superset/utils/filters.py\n"
                 "+++ b/superset/utils/filters.py\n"
                 "@@\n-    return col > lo and col < hi\n"
                 "+    return col >= lo and col <= hi\n",
            pr_merged=True, pr_state="closed",
        ),
        _completed(
            9002,
            "Saved dashboard filters not applied on first page load",
            hours_ago=33, duration_min=22, acus=6.3,
            root="Default filter state was set after the initial chart "
                 "fetch, so the first render ignored it.",
            resolution="Initialize the filter state before the first "
                       "chart data request.",
            files=[("superset-frontend/src/dashboard/reducers/"
                    "dashboardState.ts",
                    "Seed default filters before initial fetch.")],
            diff="--- a/superset-frontend/src/dashboard/reducers/"
                 "dashboardState.ts\n+++ b/...\n@@\n-  // fetch then apply\n"
                 "+  // apply default filters, then fetch\n",
            pr_merged=True, pr_state="closed",
        ),
        _completed(
            9003,
            "CSV export corrupts decimals in comma-decimal locales",
            hours_ago=26, duration_min=18, acus=5.0,
            root="CSV writer used the locale decimal separator, so values "
                 "collided with the field delimiter.",
            resolution="Force `.` as the decimal separator in CSV export "
                       "regardless of server locale.",
            files=[("superset/result_set.py",
                    "Pin CSV decimal separator to '.'.")],
            diff="--- a/superset/result_set.py\n+++ b/superset/result_set.py"
                 "\n@@\n-    df.to_csv(buf)\n"
                 "+    df.to_csv(buf, decimal='.')\n",
            pr_merged=True, pr_state="closed",
        ),
        _completed(
            9004,
            "Bar chart y-axis starts at non-zero, exaggerating change",
            hours_ago=8, duration_min=16, acus=4.7,
            root="ECharts y-axis `min` was left to auto, so small deltas "
                 "looked dramatic.",
            resolution="Default the bar-chart y-axis minimum to 0 (override "
                       "still available in chart options).",
            files=[("superset-frontend/plugins/plugin-chart-echarts/src/"
                    "Timeseries/transformProps.ts",
                    "Set yAxis.min = 0 by default for bar charts.")],
            diff="--- a/.../transformProps.ts\n+++ b/.../transformProps.ts\n"
                 "@@\n-  yAxis: { type: 'value' },\n"
                 "+  yAxis: { type: 'value', min: 0 },\n",
            pr_merged=False, pr_state="open",
        ),
        _completed(
            9005,
            "Chart tooltip shows raw metric name instead of label",
            hours_ago=20, duration_min=12, acus=3.4,
            root="Tooltip formatter read `metric.name` instead of the "
                 "verbose `metric.label`.",
            resolution="Prefer the human label in the tooltip, fall back "
                       "to the name.",
            files=[("superset-frontend/plugins/plugin-chart-echarts/src/"
                    "utils/tooltip.ts",
                    "Use verbose metric label in tooltip.")],
            diff="--- a/.../tooltip.ts\n+++ b/.../tooltip.ts\n"
                 "@@\n-  return metric.name;\n"
                 "+  return metric.label ?? metric.name;\n",
            # human reviewed and closed without merging (superseded)
            pr_merged=False, pr_state="closed",
        ),
    ]

    tasks.append(
        _completed(
            9006,
            "Very large SQL Lab result export times out intermittently",
            hours_ago=5, duration_min=27, acus=7.9,
            root="The export streamed the entire result set into memory "
                 "before writing, hitting the request timeout on large "
                 "queries.",
            resolution="Stream the result set to the CSV writer in chunks "
                       "instead of materialising it fully in memory.",
            files=[("superset/result_set.py",
                    "Chunk the CSV export instead of full in-memory "
                    "materialisation.")],
            diff="--- a/superset/result_set.py\n"
                 "+++ b/superset/result_set.py\n"
                 "@@\n-    rows = list(cursor.fetchall())\n"
                 "-    df.to_csv(buf)\n"
                 "+    for chunk in cursor.fetchmany_iter(10_000):\n"
                 "+        chunk.to_csv(buf, header=buf.tell() == 0)\n",
            pr_merged=True, pr_state="closed",
        )
    )
    return tasks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--clear", action="store_true",
        help="remove only demo-marked rows, then exit",
    )
    args = ap.parse_args()
    store = Store(os.getenv("DATA_DIR", "./data"))

    if args.clear:
        removed = 0
        for t in store.load_all():
            if t.get("demo"):
                store.path_for(t["internal_id"]).unlink(missing_ok=True)
                removed += 1
        print(f"Cleared {removed} demo row(s) from {store.data_dir}")
        return 0

    tasks = _demo_tasks()
    for t in tasks:
        store.save_task(t)
    comp = sum(1 for t in tasks if t["status"] == "completed")
    merged = sum(1 for t in tasks if t.get("pr_merged"))
    failed = sum(1 for t in tasks if t["status"] == "failed")
    print(
        f"Seeded {len(tasks)} demo row(s) into {store.data_dir}\n"
        f"  completed={comp}  failed={failed}  "
        f"running={len(tasks) - comp - failed}\n"
        f"  success_rate={comp}/{comp + failed} = "
        f"{round(100 * comp / (comp + failed))}%\n"
        f"  merged={merged}/{comp} = "
        f"{round(100 * merged / comp)}%  (human-merged PRs)\n"
        "Open the dashboard to view. Remove with: "
        "python scripts/seed_demo_data.py --clear"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
