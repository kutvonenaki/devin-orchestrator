"""Programmatic proof of the demo premise: the REAL superset compare.py
returns inf for a zero comparison value. Skips cleanly if superset/ absent.

This lives in OUR test suite, never handed to Devin.
"""

from __future__ import annotations

import enum
import importlib.util
import sys
import types
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

COMPARE_PY = (
    Path(__file__).resolve().parent.parent
    / "superset/superset/utils/pandas_postprocessing/compare.py"
)

pytestmark = pytest.mark.skipif(
    not COMPARE_PY.exists(), reason="superset/ fork not present"
)


class _PPC(str, enum.Enum):
    DIFF = "difference"
    PCT = "percentage"
    RAT = "ratio"


def _load_real_compare():
    def mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m

    def validate_column_args(*_a):
        def wrap(func):
            def wrapped(df, **opts):
                return func(df, **opts)
            return wrapped
        return wrap

    mod("flask_babel", gettext=lambda s: s)
    mod("superset")
    mod("superset.constants", PandasPostprocessingCompare=_PPC)
    mod("superset.exceptions", InvalidPostProcessingError=Exception)
    mod("superset.utils")
    mod("superset.utils.core", TIME_COMPARISON="__")
    mod("superset.utils.pandas_postprocessing")
    mod("superset.utils.pandas_postprocessing.utils",
        validate_column_args=validate_column_args)

    spec = importlib.util.spec_from_file_location("_real_compare", COMPARE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.compare


def test_zero_denominator_yields_inf():
    compare = _load_real_compare()
    df = pd.DataFrame({"a": [10.0, 25.0, 8.0], "b": [5.0, 0.0, 4.0]})
    pct = compare(df, source_columns=["a"], compare_columns=["b"],
                  compare_type=_PPC.PCT, precision=2)["percentage__a__b"]
    assert float("inf") in list(pct), f"expected inf, got {list(pct)}"
