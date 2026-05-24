"""Unit tests for Comparison Tool significance sync helpers."""

import pandas as pd

# Import helpers from streamlit_app without running Streamlit.
import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("streamlit_app_sig", _ROOT / "streamlit_app.py")
_mod = importlib.util.module_from_spec(_spec)
sys.modules["streamlit_app_sig"] = _mod
_spec.loader.exec_module(_mod)

player_last_name = _mod.player_last_name
_compare_sig_sync_caption = _mod._compare_sig_sync_caption
_compare_sig_player_range_tuple = _mod._compare_sig_player_range_tuple
_compare_sig_range_column_label = _mod._compare_sig_range_column_label
_is_full_compare_year_range = _mod._is_full_compare_year_range
_filter_player_seasons_for_sig = _mod._filter_player_seasons_for_sig


def _mini_yearly():
    return pd.DataFrame([
        {"playerID": "ohtani", "yearID": 2018, "fullName": "Shohei Ohtani", "HR": 22,
         "birthYear": 1994, "birthMonth": 7, "birthDay": 5},
        {"playerID": "ohtani", "yearID": 2023, "fullName": "Shohei Ohtani", "HR": 44,
         "birthYear": 1994, "birthMonth": 7, "birthDay": 5},
        {"playerID": "ramirez", "yearID": 2018, "fullName": "Jose Ramirez", "HR": 39,
         "birthYear": 1993, "birthMonth": 9, "birthDay": 17},
        {"playerID": "ramirez", "yearID": 2023, "fullName": "Jose Ramirez", "HR": 36,
         "birthYear": 1993, "birthMonth": 9, "birthDay": 17},
    ])


def test_player_last_name():
    assert player_last_name("Shohei Ohtani") == "Ohtani"
    assert player_last_name("Jose Ramirez") == "Ramirez"
    assert player_last_name("Aaron Judge") == "Judge"


def test_sync_caption_year_range():
    df = _mini_yearly()
    ids = ["ohtani", "ramirez"]
    cap = _compare_sig_sync_caption("Season Year", (2020, 2022), (16, 50), df, ids)
    assert cap == "Synced to comparison year range: 2020–2022"


def test_sync_caption_full_career():
    df = _mini_yearly()
    ids = ["ohtani", "ramirez"]
    assert _is_full_compare_year_range(df, ids, (2018, 2023))
    cap_full = _compare_sig_sync_caption("Season Year", (2018, 2023), (16, 50), df, ids)
    assert cap_full == "Using full available career range"


def test_sync_caption_age_range():
    df = _mini_yearly()
    cap = _compare_sig_sync_caption("Player Age", (2018, 2023), (20, 30), df, ["ohtani"])
    assert cap == "Synced to comparison age range: 20–30"


def test_range_column_labels():
    assert _compare_sig_range_column_label("Ohtani", "Season Year") == "Ohtani years"
    assert _compare_sig_range_column_label("Ramirez", "Player Age") == "Ramirez ages"


def test_player_range_year_sync():
    rng = _compare_sig_player_range_tuple(
        2018, 2023,
        compare_x_axis_mode="Season Year",
        compare_year_range=(2018, 2023),
        compare_age_range=(16, 50),
        use_full_career=False,
    )
    assert rng == (2018, 2023)


def test_player_range_age_sync():
    rng = _compare_sig_player_range_tuple(
        2018, 2023,
        compare_x_axis_mode="Player Age",
        compare_year_range=(2018, 2023),
        compare_age_range=(20, 30),
        use_full_career=False,
    )
    assert rng == (20, 30)


def test_filter_by_year_range():
    df = _mini_yearly()
    out = _filter_player_seasons_for_sig(df, "ohtani", "Season Year", (2018, 2020))
    assert len(out) == 1
    assert int(out.iloc[0]["yearID"]) == 2018
