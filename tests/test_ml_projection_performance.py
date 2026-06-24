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
_build_sim_index = _mod._build_ml_similarity_index
_query_sim = _mod._query_ml_similarity_comps
_get_age = _mod._ml_get_age_curve_from_pack
_get_comp = _mod._ml_get_train_companions
_safe_df = _mod.safe_get_dataframe
_resolve = _mod._ml_resolve_tuning_session_artifacts


def test_nearest_age_adjustment_series():
    ages = pd.Series([25.0, 30.0, np.nan], index=[0, 1, 2])New Baseball UX feature request — please design and implement a draft-action system that works consistently across Draft Room, Live Draft Room, Queue, Watchlist, and Tracked Players.

Goal:
A user should be able to draft a player from anywhere in the app where that player is visible, provided it is currently the user's pick.

Requirements

1. Queue Players
- Every player in Queue Players should have a Draft button.
- If it is the user's pick:
    - Draft the player immediately to the next open pick.
    - Remove player from queue after successful draft.
- If it is not the user's pick:
    - Disable the Draft button or show "Not Your Pick".

2. Watchlist
- Every player in Watchlist should have a Draft button.
- Same rules as Queue Players.
- Drafting should not require navigating back to Draft Room.

3. Tracked Players
- Every tracked player should have a Draft button.
- Same rules as Queue Players.
- User can analyze a player, track them, and draft directly from that panel.

4. Live Draft Room Persistence
Current workflow should not require staying on the Live Draft page.

Requirements:
- User can leave Live Draft Room.
- User can visit other pages.
- User can return later.
- Live draft state remains synchronized.
- Queue remains synchronized.
- Watchlist remains synchronized.
- Current pick remains synchronized.
- Draft board remains synchronized.

5. Live Draft Queue Panel
Add a dedicated Queue section on the Live Draft Room page.

Display:
- Queue order
- Player name
- Position
- Team
- Draft button

Behavior:
- Draft directly from queue if it is the user's turn.
- Automatically remove drafted player from queue.
- Update board immediately.

6. Unified Draft Action
Create a single draft action path used by:
- Draft Room
- Live Draft Room
- Queue Players
- Watchlist
- Tracked Players
- Any future player cards

One source of truth:
draft_player(player_id)

This should:
- Validate user's turn
- Validate player available
- Update canonical board
- Update live draft state
- Remove from queue if present
- Refresh projections and recommendations
- Sync cloud state

7. Permission Rules
If user's pick:
- Draft button enabled

If not user's pick:
- Draft button disabled
OR
- Show explanatory message

Never allow accidental drafting out of turn.

Design First
Please design the architecture and UX flow first before major implementation. Focus on creating one unified draft action system instead of separate draft logic in multiple locations.
    curve = pd.DataFrame({
        "Stat": ["HR", "HR", "HR"],
        "Age": [24, 26, 30],
        "Age Adjustment": [1.0, 2.0, -0.5],
    })
    out = _nearest(ages, curve, "HR")
    assert out.iloc[0] == 1.0  # age 25 nearest to bucket 24
    assert out.iloc[1] == -0.5
    assert out.iloc[2] == 0.0


def test_ml_similarity_index_reuse_across_k():
    train = pd.DataFrame({
        "playerID": [f"p{i}" for i in range(8)],
        "age_entering_year": [25, 26, 27, 28, 29, 30, 31, 32],
        "age_squared": [625, 676, 729, 784, 841, 900, 961, 1024],
        "hist_AB_total": [500] * 8,
        "G_last": [140] * 8,
        "AB_last": [500] * 8,
        "HR_last": [10 + i for i in range(8)],
        "target_HR": [12 + i for i in range(8)],
    })
    current = train.iloc[:2].copy()
    feature_cols = ("age_entering_year", "age_squared", "hist_AB_total", "G_last", "AB_last", "HR_last")
    idx = _build_sim_index(train, feature_cols)
    assert idx is not None
    c5 = _query_sim(idx, current, k_neighbors=5)
    c3 = _query_sim(idx, current, k_neighbors=3)
    assert len(c5) == 2
    assert len(c3) == 2
    assert (c5["Similar Player Sample"] >= c3["Similar Player Sample"]).all()


def test_safe_get_dataframe_avoids_or_truthiness():
    full = pd.DataFrame({"a": [1, 2]})
    empty = pd.DataFrame()
    out = _safe_df(empty, full)
    assert len(out) == 2
    out2 = _safe_df(None, empty)
    assert out2.empty


def test_ml_resolve_tuning_session_artifacts():
    primary = pd.DataFrame({"playerID": ["a"], "Predicted HR": [40]})
    fallback = pd.DataFrame({"playerID": ["b"], "Predicted HR": [30]})
    result = {"ml_training_df": primary, "pred_df": primary}
    base = {"ml_training_df": fallback, "ml_feature_cols": ["x"], "ml_models": {"HR": {}}}
    train, cols, models, pred, age, comp = _resolve(result, base)
    assert len(train) == 1
    assert train.iloc[0]["playerID"] == "a"
    assert cols == ["x"]
    assert "HR" in models
    assert len(pred) == 1


def test_ml_pack_helpers_avoid_dataframe_truthiness():
    """Regression: never evaluate DataFrame in `or` / `if df` context."""
    empty_curve = pd.DataFrame(columns=["Stat", "Age", "Age Adjustment"])
    pack = {"age_curve_df": empty_curve, "train_companions": pd.DataFrame()}
    train = pd.DataFrame({
        "playerID": ["a", "a"],
        "predict_year": [2022, 2023],
        "age_entering_year": [27, 28],
        "target_HR": [20, 22],
    })
    curve = _get_age(pack, train)  # must not raise ambiguous DataFrame truth-value error
    assert isinstance(curve, pd.DataFrame)
    comp = _get_comp(pack, train)
    assert isinstance(comp, pd.DataFrame)
    assert len(comp) == 1


def test_ml_signatures_split_tuning_from_base():
    yl = pd.DataFrame({"yearID": [2020, 2021, 2022, 2023]})
    b1 = _base_sig(yl, 3, 50, 150)
    b2 = _base_sig(yl, 3, 50, 150)
    assert b1 == b2
    t1 = _tuning_sig(0.2, 0.5, 0.1, 10, 300, "Balanced")
    t2 = _tuning_sig(0.3, 0.5, 0.1, 10, 300, "Balanced")
    assert t1 != t2
