"""ML projection helper tests (no full Streamlit run)."""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("streamlit_app_ml", _ROOT / "streamlit_app.py")
_mod = importlib.util.module_from_spec(_spec)
sys.modules["streamlit_app_ml"] = _mod
_spec.loader.exec_module(_mod)

_nearest = _mod._nearest_age_adjustment_series
_base_sig = _mod._ml_base_run_signature
_tuning_sig = _mod._ml_tuning_run_signature


def test_nearest_age_adjustment_series():
    ages = pd.Series([25.0, 30.0, np.nan], index=[0, 1, 2])
    curve = pd.DataFrame({
        "Stat": ["HR", "HR", "HR"],
        "Age": [24, 26, 30],
        "Age Adjustment": [1.0, 2.0, -0.5],
    })
    out = _nearest(ages, curve, "HR")
    assert out.iloc[0] == 1.0  # age 25 nearest to bucket 24
    assert out.iloc[1] == -0.5
    assert out.iloc[2] == 0.0


def test_ml_signatures_split_tuning_from_base():
    yl = pd.DataFrame({"yearID": [2020, 2021, 2022, 2023]})
    b1 = _base_sig(yl, 3, 50, 150)
    b2 = _base_sig(yl, 3, 50, 150)
    assert b1 == b2
    t1 = _tuning_sig(0.2, 0.5, 0.1, 10, 300, "Balanced")
    t2 = _tuning_sig(0.3, 0.5, 0.1, 10, 300, "Balanced")
    assert t1 != t2
