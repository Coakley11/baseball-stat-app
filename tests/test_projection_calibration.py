"""Tests for ML final calibration + draft-lab stabilization helpers."""

import numpy as np
import pandas as pd

import projection_calibration as proj_cal


def test_calibration_blend_weight_favors_stars():
    conf = pd.Series([0.8, 0.4])
    elite = pd.Series([0.9, 0.1])
    vol = pd.Series([0.2, 0.6])
    star = pd.Series([True, False])
    very_lim = pd.Series([False, True])
    w_star = proj_cal.calibration_blend_weight(conf, elite, vol, star, very_lim, counting=True)
    w_noise = proj_cal.calibration_blend_weight(conf, elite, vol, star, very_lim, counting=True)
    assert float(w_star.iloc[0]) < float(w_noise.iloc[1])


def test_apply_ml_final_output_calibration_blends_toward_anchors():
    pred = pd.DataFrame(
        {
            "playerID": ["p1"],
            "Predicted HR": [50.0],
            "Predicted RBI": [120.0],
            "Predicted R": [100.0],
            "Predicted SB": [25.0],
            "Predicted BA": [0.320],
            "Predicted OPS": [1.050],
        }
    )
    anchors = pd.DataFrame(
        {
            "playerID": ["p1"],
            "proj_HR": [40.0],
            "proj_RBI": [100.0],
            "proj_R": [90.0],
            "proj_SB": [15.0],
            "proj_BA": [0.290],
            "proj_OPS": [0.950],
            "Projection Confidence Score": [0.35],
            "Elite Star Score": [0.2],
            "Volatility Score": [0.55],
            "Star Protected": [False],
            "Very Limited Data": [True],
        }
    )
    out = proj_cal.apply_ml_final_output_calibration(pred, anchors)
    assert out.loc[0, "Predicted HR"] < 50.0
    assert out.loc[0, "Predicted HR"] > 40.0
    assert bool(out.loc[0, "Calibration Applied"])


def test_apply_ml_final_output_calibration_elite_undershoot_guard():
    pred = pd.DataFrame(
        {
            "playerID": ["star1"],
            "Predicted HR": [30.0],
            "Predicted RBI": [88.0],
            "Predicted R": [92.0],
            "Predicted SB": [9.0],
            "Predicted BA": [0.275],
            "Predicted OPS": [0.930],
        }
    )
    anchors = pd.DataFrame(
        {
            "playerID": ["star1"],
            "proj_HR": [54.0],
            "proj_RBI": [124.0],
            "proj_R": [121.0],
            "proj_SB": [11.0],
            "proj_BA": [0.282],
            "proj_OPS": [0.970],
            "Projection Confidence Score": [0.88],
            "Elite Star Score": [0.92],
            "Volatility Score": [0.20],
            "Star Protected": [True],
            "Very Limited Data": [False],
        }
    )
    out = proj_cal.apply_ml_final_output_calibration(pred, anchors)
    assert out.loc[0, "Predicted HR"] >= 48.6


def test_apply_stabilized_counting_projections_caps_breakout():
    projection_source = pd.DataFrame(
        {
            "playerID": ["p1", "p1"],
            "yearID": [2023, 2024],
            "G": [140, 145],
            "AB": [520, 540],
            "H": [130, 150],
            "HR": [12, 35],
            "RBI": [50, 95],
            "R": [70, 90],
            "SB": [5, 8],
            "BB": [40, 45],
            "HBP": [4, 5],
            "SF": [2, 3],
            "BA": [0.250, 0.278],
            "OPS": [0.720, 0.920],
        }
    )
    projection_source = proj_cal.build_projection_source(projection_source)
    pool = projection_source.groupby("playerID", as_index=False).agg(
        {
            "G": "sum",
            "AB": "sum",
            "H": "sum",
            "HR": "sum",
            "RBI": "sum",
            "R": "sum",
            "SB": "sum",
            "BB": "sum",
            "HBP": "sum",
            "SF": "sum",
            "BA": "mean",
            "OPS": "mean",
            "PA_est": "sum",
        }
    )
    pool["years_played"] = 2
    pool["avg_HR"] = 23.5
    pool["max_HR"] = 35
    pool["avg_G"] = 142.5
    pool["max_G"] = 145
    pool["latest_support_G"] = 145
    pool["latest_support_PA_est"] = 588
    pool["latest_support_HR"] = 35
    pool["avg_PA_per_G"] = 4.0
    pool["latest_support_PA_per_G"] = 4.05
    pool["avg_AB_per_PA"] = 0.90
    pool["latest_support_AB_per_PA"] = 0.91
    pool["G_trend"] = 5
    pool["HR_per_PA_trend"] = 0.0
    pool["RBI_per_PA_trend"] = 0.0
    pool["R_per_PA_trend"] = 0.0
    pool["SB_per_PA_trend"] = 0.0
    pool["std_PA_est"] = 20
    pool["std_OPS"] = 0.08
    pool["std_BA"] = 0.02
    pool["avg_BA"] = 0.264
    pool["avg_OPS"] = 0.820
    pool["latest_support_BA"] = 0.278
    pool["latest_support_OPS"] = 0.920
    pool["BA_trend"] = 0.01
    pool["OPS_trend"] = 0.04
    out = proj_cal.apply_stabilized_counting_projections(pool, projection_source)
    assert out.loc[0, "proj_HR"] < 45


def test_apply_stabilized_counting_projections_preserves_elite_slugger_floor():
    projection_source = pd.DataFrame(
        {
            "playerID": ["star1", "star1", "star1"],
            "yearID": [2022, 2023, 2024],
            "G": [148, 149, 145],
            "AB": [585, 572, 559],
            "H": [160, 158, 152],
            "HR": [44, 52, 58],
            "RBI": [106, 118, 141],
            "R": [110, 104, 122],
            "SB": [14, 11, 9],
            "BB": [96, 108, 132],
            "HBP": [4, 5, 6],
            "SF": [5, 4, 5],
            "BA": [0.274, 0.276, 0.272],
            "OPS": [0.952, 0.998, 1.113],
        }
    )
    projection_source = proj_cal.build_projection_source(projection_source)
    pool = projection_source.groupby("playerID", as_index=False).agg(
        {
            "G": "sum",
            "AB": "sum",
            "H": "sum",
            "HR": "sum",
            "RBI": "sum",
            "R": "sum",
            "SB": "sum",
            "BB": "sum",
            "HBP": "sum",
            "SF": "sum",
            "BA": "mean",
            "OPS": "mean",
            "PA_est": "sum",
        }
    )
    pool["years_played"] = 3
    pool["avg_HR"] = 51.3
    pool["max_HR"] = 58
    pool["avg_RBI"] = 121.7
    pool["max_RBI"] = 141
    pool["avg_R"] = 112.0
    pool["max_R"] = 122
    pool["avg_G"] = 147.3
    pool["max_G"] = 149
    pool["latest_support_G"] = 145
    pool["latest_support_PA_est"] = 702
    pool["latest_support_HR"] = 58
    pool["latest_support_RBI"] = 141
    pool["latest_support_R"] = 122
    pool["avg_PA_per_G"] = 4.78
    pool["latest_support_PA_per_G"] = 4.84
    pool["avg_AB_per_PA"] = 0.80
    pool["latest_support_AB_per_PA"] = 0.80
    pool["G_trend"] = 0
    pool["HR_per_PA_trend"] = 0.002
    pool["RBI_per_PA_trend"] = 0.001
    pool["R_per_PA_trend"] = 0.001
    pool["SB_per_PA_trend"] = -0.0005
    pool["std_PA_est"] = 12
    pool["std_OPS"] = 0.07
    pool["std_BA"] = 0.003
    pool["avg_BA"] = 0.274
    pool["avg_OPS"] = 1.021
    pool["latest_support_BA"] = 0.272
    pool["latest_support_OPS"] = 1.113
    pool["BA_trend"] = -0.001
    pool["OPS_trend"] = 0.015
    out = proj_cal.apply_stabilized_counting_projections(pool, projection_source)
    assert out.loc[0, "Elite Star Score"] >= 0.60
    assert out.loc[0, "proj_HR"] >= 46
