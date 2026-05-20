"""JSON-file task store (no SQLite).

One file per issue at ``${DATA_DIR}/issue-<n>.json``. Atomic writes via
tempfile + os.replace. Metrics (MTTR / success rate / throughput) are computed
in Python over load_all() — trivial at demo scale.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


class Store:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, internal_id: str) -> Path:
        return self.data_dir / f"{internal_id}.json"

    def exists(self, internal_id: str) -> bool:
        return self.path_for(internal_id).exists()

    def save_task(self, task: dict[str, Any]) -> None:
        path = self.path_for(task["internal_id"])
        fd, tmp = tempfile.mkstemp(dir=self.data_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(task, f, indent=2, default=str)
            os.replace(tmp, path)  # atomic on same filesystem
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def load_task(self, internal_id: str) -> Optional[dict[str, Any]]:
        path = self.path_for(internal_id)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def load_all(self) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for p in self.data_dir.glob("*.json"):
            try:
                tasks.append(json.loads(p.read_text()))
            except (json.JSONDecodeError, OSError):
                continue
        tasks.sort(key=lambda t: t.get("start_time") or "", reverse=True)
        return tasks

    def metrics(self, tasks: Optional[list[dict]] = None) -> dict[str, Any]:
        tasks = self.load_all() if tasks is None else tasks
        completed = [t for t in tasks if t.get("status") == "completed"]
        failed = [t for t in tasks if t.get("status") == "failed"]
        active = [
            t for t in tasks if t.get("status") in ("initializing", "running")
        ]

        durations: list[float] = []
        for t in completed:
            st, et = _parse(t.get("start_time")), _parse(t.get("end_time"))
            if st and et:
                d = (et - st).total_seconds()
                if d >= 0:
                    durations.append(d)
        avg_mttr = round(sum(durations) / len(durations), 1) if durations else None

        decided = len(completed) + len(failed)
        success_rate = round(len(completed) / decided, 3) if decided else None

        # Human-validated outcome: of the PRs Devin delivered, how many a
        # person actually merged. `merge_rate` uses completed as the
        # denominator (everything Devin shipped a PR for); still-open PRs
        # simply haven't been merged *yet* — it's a lagging metric.
        merged = [t for t in completed if t.get("pr_merged")]
        merge_rate = (
            round(len(merged) / len(completed), 3) if completed else None
        )

        starts = [s for s in (_parse(t.get("start_time")) for t in tasks) if s]
        throughput = None
        if len(starts) >= 2:
            span_h = (max(starts) - min(starts)).total_seconds() / 3600
            if span_h > 0:
                throughput = round(len(starts) / span_h, 2)

        acus = [
            t["acus_consumed"]
            for t in tasks
            if isinstance(t.get("acus_consumed"), (int, float))
        ]
        total_acus = round(sum(acus), 2) if acus else None

        return {
            "total": len(tasks),
            "completed": len(completed),
            "failed": len(failed),
            "active": len(active),
            "merged": len(merged),
            "avg_mttr_seconds": avg_mttr,
            "success_rate": success_rate,
            "merge_rate": merge_rate,
            "throughput_per_hour": throughput,
            "total_acus": total_acus,
        }
