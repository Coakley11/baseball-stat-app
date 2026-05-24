"""Tests for projection_breakdown helpers."""

import numpy as np
import pandas as pd

import projection_breakdown as pb


def test_classify_trend_direction_counting_and_rate():
    assert pb.classify_trend_direction(2.5, kind="counting") == "improving"
    assert pb.classify_trend_direction(-2.0, kind="counting") == "declining"
    assert pb.classify_trend_direction(0.2, kind="counting") == "stable"
    assert pb.classify_trend_direction(0.02, kind="rate") == "improving"
    assert pb.classify_trend_direction(-0.02, kind="rate") == "declining"
    assert pb.classify_trend_direction(0.001, kind="rate") == "stable"
    assert pb.classify_trend_direction(np.nan, kind="counting") == "unknown"


def test_row_has_stabilized_projection():
    legacy = pd.Series({"proj_HR": 30, "HR_trend": 1.2})
    stabilized = pd.Series({
        "proj_HR": 42,
        "Projection Confidence Score": 0.72,
        "proj_G": 140,
        "Realistic Base Projection Score": 0.81,
    })
    assert not pb.row_has_stabilized_projection(legacy)
    assert pb.row_has_stabilized_projection(stabilized)


def test_build_trend_cards_includes_r_and_rbi():
    row = pd.Series({
        "HR_trend": 1.5,
        "R_trend": 2.0,
        "RBI_trend": -0.5,
        "SB_trend": 0.1,
        "2B_trend": 0.3,
        "3B_trend": -0.1,
        "BA_trend": 0.012,
        "OPS_trend": 0.025,
    })
    hist = pd.DataFrame({
        "yearID": [2023, 2024, 2025],
        "HR": [30, 35, 40],
        "R": [80, 85, 90],
    })
    cards = pb.build_trend_cards(row, hist)
    ids = {c["id"] for c in cards}
    assert {"HR", "R", "RBI", "SB", "2B", "3B", "BA", "OPS"} <= ids
    hr = next(c for c in cards if c["id"] == "HR")
    assert hr["direction"] == "improving"
    assert hr["arrow"] == "↑"


def test_build_projection_breakdown_bundle_stabilized_flag():
    row = pd.Series({
        "proj_HR": 40,
        "proj_OPS": 0.900,
        "Projection Confidence Score": 0.8,
        "proj_G": 145,
        "HR_trend": 1.0,
        "OPS_trend": 0.01,
    })
    bundle = pb.build_projection_breakdown_bundle(
        "Test Player",
        row,
        data_source="unified_stabilized_pool",
        projection_system=pb.PROJECTION_SYSTEM_LABEL,
    )
    assert bundle["stabilized"] is True
    assert bundle["snapshot"]["projections"]["HR"] == 40
    assert len(bundle["trend_cards"]) == 8
