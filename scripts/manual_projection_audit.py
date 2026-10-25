"""Manual cross-system projection audit for selected players.

Run from repo root:
    python scripts/manual_projection_audit.py
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
SA = BASE / "streamlit_app.py"
sys.path.insert(0, str(BASE))


class _StreamlitShim(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {}
        self.sidebar = types.SimpleNamespace()

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in ("cache_data", "cache_resource", "dialog", "fragment"):
            return lambda *a, **kwargs: (lambda fn: fn)
        if name in ("spinner", "expander"):
            class _Ctx:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            return lambda *a, **k: _Ctx()
        if name == "columns":
            return lambda spec: [types.SimpleNamespace()] * (spec if isinstance(spec, int) else len(spec))
        return lambda *a, **k: None


sys.modules["streamlit"] = _StreamlitShim()
for mod_name in ("workflow_sidebar", "page_transfers", "page_state", "draft_strategy_intel", "draft_team_fit"):
    __import__(mod_name)

import app_tutorial  # noqa: E402,F401
import projection_calibration as proj_cal  # noqa: E402
from projection_style import get_draft_projection_factors  # noqa: E402

_app_src = SA.read_text(encoding="utf-8").splitlines()
_ui_start = next(i for i, line in enumerate(_app_src) if "st.set_page_config" in line)
_def_start = next(i for i, line in enumerate(_app_src) if line.startswith("def fmt_int"))
_render_start = next(i for i, line in enumerate(_app_src) if line.startswith("_APP_RENDER_START"))
_exec_src = "\n".join(_app_src[:_ui_start] + _app_src[_def_start:_render_start])
_g: dict = {
    "__file__": str(SA),
    "__name__": "streamlit_app_defs",
    "np": np,
    "pd": pd,
    "Path": Path,
    "re": __import__("re"),
    "time": __import__("time"),
    "uuid": __import__("uuid"),
    "Counter": __import__("collections").Counter,
    "plt": __import__("matplotlib.pyplot"),
    "alt": __import__("altair"),
    "MaxNLocator": __import__("matplotlib.ticker", fromlist=["MaxNLocator"]).MaxNLocator,
    "io": __import__("io"),
    "unicodedata": __import__("unicodedata"),
    "hashlib": __import__("hashlib"),
    "st": sys.modules["streamlit"],
    "wf_sb": sys.modules["workflow_sidebar"],
    "pg_xfer": sys.modules["page_transfers"],
    "pg_state": sys.modules["page_state"],
    "draft_strategy_line": sys.modules["draft_strategy_intel"].draft_strategy_line,
    "team_fit_summary_line": sys.modules["draft_team_fit"].team_fit_summary_line,
    "proj_cal": proj_cal,
    "get_draft_projection_factors": get_draft_projection_factors,
    "app_tutorial": app_tutorial,
}
exec(compile(_exec_src, str(SA), "exec"), _g, _g)


from projection_validation import ML_PROJECTION_VALIDATION_GROUPS, ML_PROJECTION_VALIDATION_PLAYERS

STAT_PAIRS = [
    ("HR", "Predicted HR", "proj_HR"),
    ("RBI", "Predicted RBI", "proj_RBI"),
    ("R", "Predicted R", "proj_R"),
    ("SB", "Predicted SB", "proj_SB"),
    ("AVG", "Predicted BA", "proj_BA"),
    ("OPS", "Predicted OPS", "proj_OPS"),
]


def _resolve(df, name: str, resolver):
    resolved = resolver(df, name)
    if resolved:
        return resolved
    n = name.strip().lower()
    names = df.get("fullName", pd.Series(dtype=str)).astype(str)
    exact = names[names.str.strip().str.lower() == n]
    if not exact.empty:
        return str(exact.iloc[0])
    contains = names[names.str.lower().str.contains(n.split()[-1], na=False)]
    if not contains.empty:
        return str(contains.iloc[0])
    return None


def _fmt(v, rate=False):
    if pd.isna(v):
        return "NA"
    return f"{float(v):.3f}" if rate else f"{float(v):.1f}"


def _normalize_series(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce").fillna(0)
    lo, hi = x.min(), x.max()
    if pd.isna(lo) or pd.isna(hi) or hi <= lo:
        return pd.Series(0.5, index=x.index)
    return (x - lo) / (hi - lo)


def _compute_ml_fantasy_value(pred_df: pd.DataFrame) -> pd.Series:
    out = pd.Series(0.0, index=pred_df.index)
    weights = {
        "Predicted R": 0.12,
        "Predicted HR": 0.22,
        "Predicted RBI": 0.20,
        "Predicted SB": 0.14,
        "Predicted BA": 0.12,
        "Predicted OPS": 0.20,
    }
    for col, w in weights.items():
        if col in pred_df.columns:
            out += _normalize_series(pred_df[col]) * w
    return _normalize_series(out)


def main() -> int:
    load_data = _g["load_data"]
    load_fantasypros_market_data = _g["load_fantasypros_market_data"]
    build_base_ml_predictions = _g["build_base_ml_predictions"]
    apply_advanced_projection_adjustments = _g["apply_advanced_projection_adjustments"]
    build_stabilized_projection_anchors = _g["build_stabilized_projection_anchors"]
    build_draft_lab_player_pool = _g["build_draft_lab_player_pool"]
    _resolve_consistency_player_name = _g["_resolve_consistency_player_name"]
    ML_TARGET_STATS = _g["ML_TARGET_STATS"]
    assemble_projection_breakdown_bundle = _g["assemble_projection_breakdown_bundle"]

    _, yearly_df, _ = load_data()
    market_df = load_fantasypros_market_data()
    _g["yearly_df"] = yearly_df
    _g["market_df"] = market_df
    _g["year_max"] = int(pd.to_numeric(yearly_df["yearID"], errors="coerce").max())

    ml_training_df, ml_feature_cols, _, current_rows, base_pred_df = build_base_ml_predictions(
        yearly_df, 3, 150, max_player_pool=450
    )
    pred_df, _, _ = apply_advanced_projection_adjustments(
        base_pred_df,
        current_rows,
        ml_training_df,
        ml_feature_cols,
        ML_TARGET_STATS,
        regression_strength=0.20,
        age_strength=0.50,
        comp_weight=0.10,
        k_neighbors=10,
        refresh_token=1,
    )
    anchor_ids = tuple(sorted(str(x) for x in pred_df["playerID"].astype(str).unique()))
    anchors = build_stabilized_projection_anchors(yearly_df, anchor_ids, lookback=5)
    if not anchors.empty:
        pred_df = proj_cal.apply_ml_final_output_calibration(pred_df, anchors)
    pred_df["ML Fantasy Value"] = _compute_ml_fantasy_value(pred_df)

    draft_pool = build_draft_lab_player_pool(
        yearly_df,
        market_df,
        draft_window=5,
        fantasy_format="5x5 Roto",
        projection_style="Balanced",
    )
    try:
        live_pool = _g["get_cached_unified_projection_pool_live"]()
    except Exception:
        # In headless runs this cache can depend on UI globals; use draft pool as live proxy.
        live_pool = draft_pool.copy()

    print("=== Manual Projection Audit ===")
    print(f"ML rows={len(pred_df)} | DraftLab rows={len(draft_pool)} | Live rows={len(live_pool)}")

    for group, players in ML_PROJECTION_VALIDATION_GROUPS.items():
        print(f"\n## Group: {group}")
        for pname in players:
            ml_name = _resolve(pred_df, pname, _resolve_consistency_player_name)
            lab_name = _resolve(draft_pool, pname, _resolve_consistency_player_name)
            live_name = _resolve(live_pool, pname, _resolve_consistency_player_name)
            print(f"\n### {pname}")
            if not ml_name:
                print("ML: missing")
                continue
            ml_row = pred_df[pred_df["fullName"].astype(str) == ml_name].iloc[0]
            lab_row = draft_pool[draft_pool["fullName"].astype(str) == lab_name].iloc[0] if lab_name else pd.Series(dtype=object)
            live_row = live_pool[live_pool["fullName"].astype(str) == live_name].iloc[0] if live_name else pd.Series(dtype=object)
            bundle = assemble_projection_breakdown_bundle(pname)
            bd_proj = bundle.get("snapshot", {}).get("projections", {})
            bd_conf = bundle.get("snapshot", {}).get("confidence", {})
            for label, ml_col, proj_col in STAT_PAIRS:
                rate = label in ("AVG", "OPS")
                ml_val = pd.to_numeric(ml_row.get(ml_col), errors="coerce")
                lab_val = pd.to_numeric(lab_row.get(proj_col), errors="coerce") if not lab_row.empty else np.nan
                live_val = pd.to_numeric(live_row.get(proj_col), errors="coerce") if not live_row.empty else np.nan
                bd_key = "BA" if label == "AVG" else label
                bd_val = pd.to_numeric(bd_proj.get(bd_key), errors="coerce")
                print(
                    f"{label:>3}: ML={_fmt(ml_val, rate)} | DraftLab={_fmt(lab_val, rate)} | "
                    f"Breakdown={_fmt(bd_val, rate)} | Live={_fmt(live_val, rate)}"
                )
            print(
                "EFV: "
                f"ML={_fmt(pd.to_numeric(ml_row.get('ML Fantasy Value'), errors='coerce'))} | "
                f"DraftLab={_fmt(pd.to_numeric(lab_row.get('Expected Fantasy Value'), errors='coerce')) if not lab_row.empty else 'NA'} | "
                f"Live={_fmt(pd.to_numeric(live_row.get('Expected Fantasy Value'), errors='coerce')) if not live_row.empty else 'NA'}"
            )
            print(
                "Risk: "
                f"ML={ml_row.get('Projection Confidence', 'NA')} ({_fmt(pd.to_numeric(ml_row.get('Projection Confidence Score'), errors='coerce'))}) "
                f"warn='{ml_row.get('Projection Warning', '')}' | "
                f"Breakdown conf={bd_conf.get('label', 'NA')} score={_fmt(pd.to_numeric(bd_conf.get('score'), errors='coerce'))}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
