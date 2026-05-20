"""Self-contained HTML dashboard (no external assets).

Server-rendered; auto-refreshes via a meta tag (zero JS, demo-robust).
Uses native <details> for per-task expansion.
"""

from __future__ import annotations

import html
from typing import Any

def _display_status(task: dict) -> tuple[str, str]:
    """Lifecycle-aware badge: a 'completed' run is really 'PR created' until
    a human merges (→ 'merged') or closes it (→ 'PR closed')."""
    st = task.get("status")
    if st == "initializing":
        return "initializing", "#8250df"
    if st == "running":
        return "running", "#9a6700"
    if st == "failed":
        return "failed", "#cf222e"
    if st == "completed":
        if task.get("pr_merged"):
            return "merged", "#1a7f37"
        if task.get("pr_state") == "closed":
            return "PR closed", "#6e7781"  # noqa: keep short
        return "PR open", "#0969da"
    return str(st or "—"), "#57606a"


def _esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _mttr(seconds: Any) -> str:
    if seconds is None:
        return "—"
    return f"{round(seconds / 60)} min"


def _pct(rate: Any) -> str:
    return "—" if rate is None else f"{round(rate * 100)}%"


def _acu(total: Any) -> str:
    if total is None:
        return "—"
    return f"{total:g}"


def _card(label: str, value: str) -> str:
    return (
        '<div class="card"><div class="v">'
        f"{value}</div><div class=\"l\">{label}</div></div>"
    )


def _fmt_ts(ts: Any) -> str:
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(int(ts), timezone.utc).strftime(
            "%H:%M:%S"
        )
    except (TypeError, ValueError, OSError):
        return ""


def _fmt_date(iso: Any) -> str:
    """ISO-8601 (GitHub style) -> YYYY-MM-DD; '—' if absent/unparseable."""
    if not iso:
        return "—"
    try:
        from datetime import datetime

        return datetime.fromisoformat(
            str(iso).replace("Z", "+00:00")
        ).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return "—"


def _worklog(worklog: Any) -> str:
    if not worklog:
        return ""
    rows = []
    for m in worklog:
        src = m.get("source") or "?"
        who = "user" if src == "user" else "devin"
        ts = _fmt_ts(m.get("created_at"))
        rows.append(
            f'<div class="wl {who}"><span class="wl-h">{_esc(src)}'
            f'<span class="wl-t">{ts}</span></span>'
            f'<div class="wl-m">{_esc(m.get("message"))}</div></div>'
        )
    return (
        "<details><summary>Worklog "
        f"({len(worklog)} messages)</summary>"
        f'<div class="worklog">{"".join(rows)}</div></details>'
    )


def _followups(followups: Any) -> str:
    if not followups:
        return ""
    rows = []
    for f in followups:
        reply_html = ""
        if f.get("devin_reply"):
            reply_html = (
                f'<div class="wl devin" style="margin-top:6px">'
                f'<span class="wl-h">Devin reply</span>'
                f'<div class="wl-m">{_esc(f["devin_reply"])}</div></div>'
            )
        rows.append(
            f'<div class="wl user"><span class="wl-h">'
            f'PR comment · @{_esc(f.get("user"))}'
            f'<span class="wl-t">relayed to Devin</span></span>'
            f'<div class="wl-m">{_esc(f.get("body"))}</div></div>'
            f'{reply_html}'
        )
    return (
        "<details open><summary>PR follow-ups "
        f"({len(followups)} relayed to Devin)</summary>"
        f'<div class="worklog">{"".join(rows)}</div>'
        "<small>Reviewer comments on the PR, forwarded into the live Devin "
        "session — Devin pushes the follow-up commit.</small></details>"
    )


def _detail(task: dict) -> str:
    out = task.get("structured_output") or {}
    if task.get("status") != "completed" or not out:
        if task.get("error"):
            return f'<div class="err">error: {_esc(task["error"])}</div>'
        return ""
    parts: list[str] = []
    parts.append(
        f"<p><b>Root cause:</b> {_esc(out.get('root_cause_analysis'))}</p>"
    )
    parts.append(
        f"<p><b>Resolution:</b> {_esc(out.get('resolution_summary'))}</p>"
    )
    fc = out.get("file_changes") or []
    if fc:
        rows = "".join(
            f"<li><code>{_esc(c.get('path'))}</code> — "
            f"{_esc(c.get('change_summary'))}</li>"
            for c in fc
        )
        parts.append(f"<p><b>Files changed:</b></p><ul>{rows}</ul>")
    elif out.get("files_edited"):
        rows = "".join(
            f"<li><code>{_esc(p)}</code></li>" for p in out["files_edited"]
        )
        parts.append(f"<p><b>Files edited:</b></p><ul>{rows}</ul>")
    # Authoritative diff fetched from the PR (task-level, not structured_output)
    if task.get("code_diff"):
        parts.append(
            '<p><b>Diff</b> <small>(from the PR on GitHub)</small></p>'
            f'<pre class="code">{_esc(task["code_diff"])}</pre>'
        )
    if out.get("test_command_run"):
        parts.append(
            f"<p><b>Test command:</b> <code>"
            f"{_esc(out['test_command_run'])}</code></p>"
        )
    if out.get("test_stdout"):
        parts.append(
            "<p><b>Test output:</b></p><pre class=\"code\">"
            f"{_esc(out['test_stdout'])}</pre>"
        )
    parts.append(_followups(task.get("pr_followups")))
    parts.append(_worklog(task.get("worklog")))
    return "".join(parts)


def _backlog_section(backlog: list[dict]) -> str:
    if not backlog:
        return ""
    items = "".join(
        f"<li>#{_esc(b.get('number'))} "
        + (
            f'<a href="{_esc(b.get("html_url"))}" target="_blank">'
            f"{_esc(b.get('title'))}</a>"
            if b.get("html_url")
            else _esc(b.get("title"))
        )
        + "</li>"
        for b in backlog
    )
    return (
        '<div class="backlog"><h2>Backlog — awaiting Devin '
        f"({len(backlog)})</h2><ul>{items}</ul>"
        "<small>Labelled issues the poller will pick up on its next "
        "cycle.</small></div>"
    )


def render_dashboard(
    metrics: dict, tasks: list[dict], backlog: list[dict] | None = None
) -> str:
    backlog = backlog or []
    cards = "".join(
        [
            _card("Issues solved", str(metrics.get("completed", 0))),
            _card("Avg MTTR", _mttr(metrics.get("avg_mttr_seconds"))),
            _card("Run success", _pct(metrics.get("success_rate"))),
            _card("Merged", _pct(metrics.get("merge_rate"))),
            _card("ACUs Spent", _acu(metrics.get("total_acus"))),
        ]
    )

    rows = []
    for t in tasks:
        status_label, color = _display_status(t)

        # Seeded sample rows: no fake links/detail — just enough to justify
        # the metric cards above (they ARE counted in those metrics).
        if t.get("demo"):
            rows.append(
                "<tr>"
                f"<td>#{_esc(t.get('issue_number'))}</td>"
                f"<td>{_esc(t.get('issue_title'))}"
                '<span class="demo-tag">demo</span></td>'
                f"<td>{_fmt_date(t.get('issue_created_at'))}</td>"
                f'<td><span class="badge" style="background:{color}">'
                f"{_esc(status_label)}</span></td>"
                "<td>—</td></tr>"
            )
            continue

        detail = _detail(t)
        title = _esc(t.get("issue_title")) or _esc(t.get("internal_id"))
        title_cell = (
            f"<details><summary>{title}</summary>"
            f'<div class="detail">{detail}</div></details>'
            if detail
            else title
        )
        n_followups = len(t.get("pr_followups") or [])
        if n_followups:
            title_cell += (
                f'<div class="followup-tag">↩ {n_followups} PR '
                f'follow-up{"s" if n_followups != 1 else ""} relayed to '
                "Devin</div>"
            )
        if t.get("status") in ("running", "initializing") and t.get(
            "latest_message"
        ):
            live = _esc(t["latest_message"])
            if len(live) > 160:
                live = live[:160] + "…"
            title_cell += f'<div class="live">▸ {live}</div>'
        session_url = t.get("devin_session_url")
        session_cell = (
            f'<a href="{_esc(session_url)}" target="_blank">Devin ↗</a>'
            if session_url else "—"
        )
        issue_url = t.get("issue_url")
        issue_num = f"#{_esc(t.get('issue_number'))}"
        issue_cell = (
            f'<a href="{_esc(issue_url)}" target="_blank" class="issue-link">'
            f'{issue_num} ↗</a>'
            if issue_url else issue_num
        )
        created_cell = _fmt_date(t.get("issue_created_at"))
        rows.append(
            "<tr>"
            f"<td>{issue_cell}</td>"
            f"<td>{title_cell}</td>"
            f"<td>{created_cell}</td>"
            f'<td><span class="badge" style="background:{color}">'
            f"{_esc(status_label)}</span></td>"
            f"<td>{session_cell}</td>"
            "</tr>"
        )
    table_rows = "".join(rows) or (
        '<tr><td colspan="5" class="empty">No issues processed yet.</td></tr>'
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<title>Devin autonomous issue solver</title>
<style>
 *{{box-sizing:border-box}}
 body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;
   background:#f6f8fa;color:#1f2328}}
 header{{background:#0d1117;color:#fff;padding:18px 28px}}
 header h1{{margin:0;font-size:18px}}
 header p{{margin:4px 0 0;color:#9da7b3;font-size:13px}}
 main{{max-width:1080px;margin:0 auto;padding:24px}}
 .cards{{display:grid;
   grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:16px;
   margin-bottom:16px}}
 .demo-tag{{margin-left:8px;font-size:10px;text-transform:uppercase;
   letter-spacing:.05em;background:#eac54f;color:#473c00;padding:1px 6px;
   border-radius:999px;vertical-align:middle}}
 .backlog{{background:#fff;border:1px solid #d0d7de;border-radius:10px;
   padding:16px 18px;margin-bottom:24px}}
 .backlog h2{{margin:0 0 8px;font-size:15px}}
 .backlog ul{{margin:0 0 8px 18px}} .backlog small{{color:#57606a}}
 .card{{background:#fff;border:1px solid #d0d7de;border-radius:10px;
   padding:18px;text-align:center}}
 .card .v{{font-size:28px;font-weight:700}}
 .card .l{{color:#57606a;font-size:12px;margin-top:4px}}
 table{{width:100%;border-collapse:collapse;background:#fff;
   border:1px solid #d0d7de;border-radius:10px;overflow:hidden}}
 th,td{{padding:12px 14px;text-align:left;border-bottom:1px solid #eaeef2;
   vertical-align:top}}
 th{{background:#f6f8fa;font-size:12px;text-transform:uppercase;
   letter-spacing:.04em;color:#57606a}}
 .badge{{color:#fff;padding:2px 10px;border-radius:999px;font-size:12px;white-space:nowrap}}
 .empty{{text-align:center;color:#57606a;padding:28px}}
 summary{{cursor:pointer;font-weight:600}}
 .detail{{margin-top:10px;padding:12px;background:#f6f8fa;border-radius:8px}}
 .detail ul{{margin:6px 0 6px 18px}} .err{{color:#cf222e}}
 pre.code{{background:#0d1117;color:#e6edf3;padding:12px;border-radius:8px;
   overflow:auto;font-size:12px;max-height:340px}}
 code{{background:#eff1f3;padding:1px 5px;border-radius:4px}}
 a{{color:#0969da}}
 a.issue-link{{font-weight:600;white-space:nowrap}}
 .live{{margin-top:6px;font-size:12px;color:#9a6700;font-style:italic;
   max-width:540px}}
 .followup-tag{{margin-top:6px;display:inline-block;font-size:11px;
   color:#0969da;background:#ddf4ff;border:1px solid #b6e3ff;
   padding:1px 8px;border-radius:999px}}
 .worklog{{margin-top:10px;max-height:420px;overflow:auto;
   border:1px solid #eaeef2;border-radius:8px}}
 .wl{{padding:8px 12px;border-bottom:1px solid #eaeef2;font-size:12px}}
 .wl:last-child{{border-bottom:0}}
 .wl.user{{background:#f6f8fa}}
 .wl-h{{font-weight:600;text-transform:uppercase;letter-spacing:.04em;
   color:#57606a;font-size:11px;display:flex;justify-content:space-between}}
 .wl-t{{font-weight:400;color:#8c959f}}
 .wl-m{{margin-top:3px;white-space:pre-wrap;word-break:break-word}}
</style></head><body>
<header><h1>Devin autonomous issue solver</h1>
<p>Live updates every 30s</p>
</header>
<main>
 <div class="cards">{cards}</div>
 {_backlog_section(backlog)}
 <table><thead><tr><th>Issue</th><th>Title</th><th>Created</th><th>Status</th><th>Session</th>
 </tr></thead><tbody>{table_rows}</tbody></table>
</main></body></html>"""
