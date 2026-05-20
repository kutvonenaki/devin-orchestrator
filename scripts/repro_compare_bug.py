"""Local proof that the latent div-by-zero in Superset's pandas
postprocessing `compare()` actually corrupts output.

This is OUR validation harness — it is intentionally OUTSIDE superset/ so we
do NOT hand Devin the test. Devin must (re)discover and test the bug itself.

It mirrors the exact buggy expressions in
superset/utils/pandas_postprocessing/compare.py (PCT and ratio branches),
where a comparison-period value of 0 is divided into without any guard.

Run:  conda run -n devin-takehome python scripts/repro_compare_bug.py
"""

import json
import math

import numpy as np
import pandas as pd

PRECISION = 2


def buggy_pct(s_df: pd.DataFrame, c_df: pd.DataFrame) -> pd.DataFrame:
    # verbatim from compare.py (PandasPostprocessingCompare.PCT branch)
    pct_change = (s_df - c_df) / c_df
    return pct_change.astype(float).round(PRECISION)


def buggy_ratio(s_df: pd.DataFrame, c_df: pd.DataFrame) -> pd.DataFrame:
    # verbatim from compare.py (ratio branch)
    return (s_df / c_df).astype(float).round(PRECISION)


def main() -> None:
    # Source metric (current period) vs comparison metric (prior period).
    # The 2nd and 4th rows have a prior-period value of 0 — a normal real-world
    # case (a brand-new account, a metric with no activity last period, etc.).
    s_df = pd.DataFrame({"__intermediate": [10.0, 25.0, 8.0, 40.0]})
    c_df = pd.DataFrame({"__intermediate": [5.0, 0.0, 4.0, 0.0]})

    pct = buggy_pct(s_df, c_df)["__intermediate"]
    ratio = buggy_ratio(s_df, c_df)["__intermediate"]

    print("comparison column c_df :", c_df["__intermediate"].tolist())
    print("PCT  result            :", pct.tolist())
    print("ratio result           :", ratio.tolist())

    # 1. It does NOT raise ZeroDivisionError — pandas yields inf/nan silently.
    #    (planning.md's "ZeroDivisionError crash" hypothesis was wrong.)
    assert not pct.apply(np.isfinite).all(), "expected non-finite values in PCT"
    assert math.isinf(ratio.iloc[1]), "expected inf in ratio where prior == 0"
    print("\n[1] No exception raised — output silently contains inf/nan. OK")

    # 2. The realistic downstream failure: strict JSON serialization (what
    #    Superset's chart-data API effectively does) rejects inf/nan.
    payload = {"data": pct.tolist()}
    try:
        json.dumps(payload, allow_nan=False)
        raise SystemExit("UNEXPECTED: strict JSON encode did not fail")
    except ValueError as exc:
        print(f"[2] Strict JSON serialization fails downstream: {exc!r}. OK")

    # 3. Even lenient json.dumps emits invalid JSON (`Infinity` is not valid
    #    JSON), so any compliant client/parser breaks on the response.
    lenient = json.dumps(payload)
    assert "Infinity" in lenient, lenient
    print(f"[3] Lenient JSON emits invalid token: {lenient}. OK")

    print(
        "\nCONFIRMED: a 0 in the comparison period silently produces inf/nan "
        "that breaks the chart-data response. Symptom is a vague 'chart won't "
        "render / invalid response', not a Python traceback."
    )


if __name__ == "__main__":
    main()
