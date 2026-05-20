"""Run the REAL superset/utils/pandas_postprocessing/compare.py source and
prove the zero-denominator behavior through the actual function.

We avoid a full ~50-dep Superset install by injecting tiny, faithful shims for
the 4 lightweight `superset.*` symbols compare.py imports (values copied
verbatim from the repo: PandasPostprocessingCompare difference/percentage/ratio,
TIME_COMPARISON="__", validate_column_args = passthrough for valid columns,
InvalidPostProcessingError = plain exception). The compare() math itself is the
unmodified real file, loaded via importlib.

This is OUR validation — outside superset/, never handed to Devin.

Run:  conda run -n devin-takehome python scripts/verify_compare_real.py
"""

import enum
import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd

SUPERSET = Path(__file__).resolve().parent.parent / "superset"
COMPARE_PY = SUPERSET / "superset/utils/pandas_postprocessing/compare.py"


# --- faithful shims (values copied verbatim from the repo) -----------------
class PandasPostprocessingCompare(str, enum.Enum):
    DIFF = "difference"
    PCT = "percentage"
    RAT = "ratio"


class InvalidPostProcessingError(Exception):
    pass


def validate_column_args(*_argnames):
    # Real decorator only raises if referenced columns are missing; for our
    # valid inputs it is a passthrough that calls func(df, **options).
    def wrapper(func):
        def wrapped(df, **options):
            return func(df, **options)

        return wrapped

    return wrapper


def _install_shims():
    def mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
        return m

    mod("flask_babel", gettext=lambda s: s)
    mod("superset")
    mod("superset.constants", PandasPostprocessingCompare=PandasPostprocessingCompare)
    mod("superset.exceptions", InvalidPostProcessingError=InvalidPostProcessingError)
    mod("superset.utils")
    mod("superset.utils.core", TIME_COMPARISON="__")
    mod("superset.utils.pandas_postprocessing")
    mod(
        "superset.utils.pandas_postprocessing.utils",
        validate_column_args=validate_column_args,
    )


def _load_real_compare():
    spec = importlib.util.spec_from_file_location("_real_compare", COMPARE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.compare


def main() -> None:
    _install_shims()
    compare = _load_real_compare()
    PPC = PandasPostprocessingCompare

    # 1. Sanity: real compare() works normally when the prior period != 0.
    df_ok = pd.DataFrame({"a": [10.0, 20.0], "b": [5.0, 4.0]})
    out_ok = compare(
        df_ok,
        source_columns=["a"],
        compare_columns=["b"],
        compare_type=PPC.PCT,
        precision=2,
    )
    print("normal PCT  ->", out_ok["percentage__a__b"].tolist(), "(expected [1.0, 4.0])")

    # 2. The bug: a single 0 in the comparison column, via the REAL function.
    df_bug = pd.DataFrame({"a": [10.0, 25.0, 8.0], "b": [5.0, 0.0, 4.0]})
    pct = compare(
        df_bug, source_columns=["a"], compare_columns=["b"],
        compare_type=PPC.PCT, precision=2,
    )["percentage__a__b"]
    rat = compare(
        df_bug, source_columns=["a"], compare_columns=["b"],
        compare_type=PPC.RAT, precision=2,
    )["ratio__a__b"]
    print("buggy  PCT  ->", pct.tolist())
    print("buggy ratio ->", rat.tolist())

    has_inf = (~pct.apply(lambda v: v == v and abs(v) != float("inf"))).any()
    assert has_inf, "expected inf/nan from real compare() at the zero row"
    print(
        "\nCONFIRMED via the REAL compare(): a 0 in the comparison column yields "
        "inf in the returned DataFrame, with no exception and no guard.\n"
        "None of the existing tests in tests/unit_tests/pandas_postprocessing/"
        "test_compare.py use a zero comparison value, so the whole suite passes "
        "today and never exercises this path -> the bug is genuine but UNCOVERED."
    )


if __name__ == "__main__":
    main()
