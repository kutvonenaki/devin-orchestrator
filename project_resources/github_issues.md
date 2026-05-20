# Planted-bug GitHub issues

Both bugs are deliberately planted in the Superset fork. The issue text is
written from a **business-user perspective** — symptom only, no file or root
cause named. The point is to make Devin act as a *diagnostic engine*, not a
copy-paste fix-the-line task.

Each issue is labelled `bug, devin` on the fork; the `devin` label is the
human gate the poller acts on.

---

## Issue 1 — Percentage / ratio compare returns Infinity

**Status:** opened on the fork, demoed in the live run (PR #3 on the fork).

**Title:** Period-over-period % change chart returns invalid data for some metrics

**Labels:** `bug`, `devin`

**Body:**

We use dashboards with period-over-period comparison heavily for financial
reporting (this quarter vs. last quarter, MoM, etc.). Most charts work fine,
but a few of our "% change" / time-comparison charts intermittently fail to
render — the chart area shows an error or just spins, and exporting the data
is also broken for those.

**What we see**

- Affects charts using the time-comparison / "percentage change" (and "ratio")
  post-processing.
- The same chart works for most date ranges but breaks for specific ones.
- It only seems to happen for certain metrics/segments — e.g., newer accounts
  or low-activity segments where the prior period had little or no activity.
- No obvious error in the UI; the chart-data response for the failing case
  looks malformed rather than throwing a clear Python error in the logs.

**Steps to reproduce**

1. Create a chart on a dataset with a metric that can be `0` for some rows in
   the comparison period.
2. Enable time-comparison with **Percentage change** (also reproduces with
   **Ratio**).
3. Pick a date range where at least one series has a prior-period value of `0`.
4. The chart fails to render / the data response is invalid for that series.

**Impact:** Finance can't trust period-over-period dashboards — a few
zero-activity segments break the whole chart. We'd like this handled
gracefully (the comparison should degrade sensibly, not corrupt the response).

_Environment: latest `master`._

**Root cause (for our reference, not in the issue):**
`superset/utils/pandas_postprocessing/compare.py` — `(s_df - c_df) / c_df`
(PCT branch) and `s_df / c_df` (ratio branch) divide by zero when the
comparison-period value is `0`. pandas produces `inf` / `NaN`, the chart-data
JSON becomes invalid (`Infinity`), and the chart fails to render.

---

## Issue 2 — Cumulative / running totals drift low (staged, not yet opened)

**Status:** **not yet opened by design** — staged here, opened on demand via
`scripts/create_bug2_issue.sh` so a clean live run can be shown from a blank
slate.

**Title:** Cumulative / running-total columns don't tie out — YTD figures drift low

**Labels:** `bug`, `devin`

**Body:**

Our finance dashboards use "running total" / cumulative columns (YTD revenue,
cumulative bookings, etc.). The numbers look plausible but they don't
reconcile: the final YTD figure is consistently a bit **lower** than the
straight sum of the monthly values, and the gap gets worse the more rows
are in the series.

**What we see**

- Affects charts/tables using the cumulative ("running total") post-processing.
- Whole-number test data looks fine; the discrepancy shows up on real
  monetary amounts (values with cents).
- The bigger the date range / the more data points, the larger the
  shortfall — looks like a small per-row rounding/truncation that compounds.
- No error in the UI or logs; the values are just wrong, so it went unnoticed
  until Finance cross-checked YTD against the raw sum.

**Steps to reproduce**

1. Build a chart with a metric that has fractional values (e.g., revenue with
   cents).
2. Enable the cumulative / running-total post-processing (sum).
3. Compare the last cumulative value to the plain sum of the column — they
   differ, and the difference grows with row count.

**Impact:** Cumulative finance numbers can't be trusted for board/finance
reporting. We need the running total to preserve fractional precision.

_Environment: latest `master`._

**Root cause (for our reference, not in the issue):**
`superset/utils/pandas_postprocessing/cum.py` — the accumulation frame is
cast to `int` before the cumulative op (`df_cum.fillna(0).astype(int)`),
silently truncating cents on every row. The error compounds down the running
total. The comment in code is deliberate bait reading like a numerical-
stability tweak. See `planted_bug_2_cumulative.md` for the full staging
note.

---

## Why two different classes of bug

Bug #1 is a **divide-by-zero** that corrupts the response payload. Bug #2 is
a **silent precision-loss truncation** that quietly produces wrong numbers.
Both surface in the same dashboard (CFO finance view) but require completely
different diagnostic paths — the second-bug demo proves Devin generalises
beyond the first scenario.
