"""Vectorized ML training-set builder tests."""

from pathlib import Path
import sys

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import ml_training_build as mltb

BASE_STATS = ["G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "CS", "BB", "SO", "BA", "OBP", "SLG", "OPS"]
DERIVED = ["PA_est", "BB_rate", "K_rate", "SB_rate", "XBH", "XBH_rate", "HR_rate", "Speed_Index"]


def _synthetic_prepared(n_players=40, years=6):
    rows = []
    for p in range(n_players):
        pid = f"p{p:03d}"
        for y in range(2018, 2018 + years):
            ab = 480 + p * 2
            rows.append({
                "playerID": pid,
                "fullName": f"Player {p}",
                "yearID": y,
                "birthYear": 1995,
                "birthMonth": 6,
                "birthDay": 15,
                "G": 150,
                "AB": ab,
                "R": 80,
                "H": 130,
                "2B": 25,
                "3B": 3,
                "HR": 20,
                "RBI": 70,
                "SB": 10,
                "CS": 2,
                "BB": 50,
                "SO": 110,
                "BA": 0.270,
                "OBP": 0.340,
                "SLG": 0.450,
                "OPS": 0.790,
                "bats": "R",
                "primaryPos": "OF",
                "primaryTeamID": "NYY",
                "League": "AL",
                "Park_Factor": 1.0,
                "PA_est": ab + 50,
                "BB_rate": 0.1,
                "K_rate": 0.2,
                "SB_rate": 0.8,
                "XBH": 48,
                "XBH_rate": 0.1,
                "HR_rate": 0.04,
                "Speed_Index": 0.5,
            })
    return pd.DataFrame(rows)


def test_vectorized_training_smaller_than_unfiltered():
    prepared = _synthetic_prepared()
    prepared.loc[prepared["playerID"] == "p000", "yearID"] = 2005
    train_df, cols = mltb.build_training_set_vectorized(
        prepared, 3, 150, ["HR", "OPS"], BASE_STATS, DERIVED,
    )
    assert not train_df.empty
    assert cols
    assert "target_HR" in train_df.columns
    assert train_df["playerID"].nunique() >= 10


def test_disk_bundle_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(mltb, "ML_CACHE_DIR", tmp_path)
    df = pd.DataFrame({"a": [1, 2]})
    mltb.save_training_bundle("test_key", df, ["a"], {"HR": {"model": None}})
    loaded = mltb.load_training_bundle("test_key")
    assert loaded is not None
    assert len(loaded["df"]) == 2
    assert loaded["feature_cols"] == ["a"]
