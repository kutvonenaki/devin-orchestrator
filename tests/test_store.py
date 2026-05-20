from app.store import Store


def _task(i, status, start=None, end=None):
    return {
        "internal_id": f"issue-{i}",
        "issue_number": i,
        "status": status,
        "start_time": start,
        "end_time": end,
    }


def test_save_load_exists_roundtrip(tmp_path):
    s = Store(tmp_path)
    assert not s.exists("issue-1")
    s.save_task(_task(1, "running", "2026-01-01T00:00:00+00:00"))
    assert s.exists("issue-1")
    assert s.load_task("issue-1")["status"] == "running"
    assert s.load_task("issue-404") is None


def test_load_all_sorted_desc(tmp_path):
    s = Store(tmp_path)
    s.save_task(_task(1, "running", "2026-01-01T00:00:00+00:00"))
    s.save_task(_task(2, "running", "2026-01-02T00:00:00+00:00"))
    ids = [t["internal_id"] for t in s.load_all()]
    assert ids == ["issue-2", "issue-1"]


def test_metrics_math(tmp_path):
    s = Store(tmp_path)
    s.save_task(_task(1, "completed", "2026-01-01T00:00:00+00:00",
                       "2026-01-01T00:02:00+00:00"))  # 120s
    s.save_task(_task(2, "failed", "2026-01-01T00:10:00+00:00",
                       "2026-01-01T00:11:00+00:00"))
    s.save_task(_task(3, "running", "2026-01-01T00:20:00+00:00"))
    m = s.metrics()
    assert m["total"] == 3
    assert m["completed"] == 1
    assert m["failed"] == 1
    assert m["active"] == 1
    assert m["avg_mttr_seconds"] == 120.0
    assert m["success_rate"] == 0.5  # 1 / (1 completed + 1 failed)


def test_metrics_merge_rate(tmp_path):
    s = Store(tmp_path)
    c1 = _task(1, "completed", "2026-01-01T00:00:00+00:00",
               "2026-01-01T00:02:00+00:00")
    c1["pr_merged"] = True
    c2 = _task(2, "completed", "2026-01-01T00:00:00+00:00",
               "2026-01-01T00:02:00+00:00")  # PR open, not merged
    c3 = _task(3, "completed", "2026-01-01T00:00:00+00:00",
               "2026-01-01T00:02:00+00:00")
    c3["pr_merged"] = False
    s.save_task(c1)
    s.save_task(c2)
    s.save_task(c3)
    s.save_task(_task(4, "failed"))
    m = s.metrics()
    assert m["completed"] == 3
    assert m["merged"] == 1
    assert m["merge_rate"] == round(1 / 3, 3)        # merged / completed
    assert m["success_rate"] == 0.75                 # 3 / (3 + 1) decided


def test_metrics_empty(tmp_path):
    m = Store(tmp_path).metrics()
    assert m["total"] == 0
    assert m["avg_mttr_seconds"] is None
    assert m["success_rate"] is None
    assert m["merge_rate"] is None
    assert m["merged"] == 0
    assert m["total_acus"] is None


def test_metrics_total_acus(tmp_path):
    s = Store(tmp_path)
    t1 = _task(1, "completed", "2026-01-01T00:00:00+00:00",
               "2026-01-01T00:01:00+00:00")
    t1["acus_consumed"] = 2.5
    t2 = _task(2, "completed", "2026-01-01T00:02:00+00:00",
               "2026-01-01T00:03:00+00:00")
    t2["acus_consumed"] = 1.25
    t3 = _task(3, "running", "2026-01-01T00:04:00+00:00")  # no acus key
    s.save_task(t1)
    s.save_task(t2)
    s.save_task(t3)
    assert s.metrics()["total_acus"] == 3.75
