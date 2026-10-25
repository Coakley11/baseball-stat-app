"""Simulate ML Predictions page display/filter/sort logic (same helpers as Streamlit UI).

Run: python scripts/ui_ml_predictions_check.py
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
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

                def __exit__(self, *a):
                    return False

            return lambda *a, **k: _Ctx()
        return lambda *a, **k: None


sys.modules["streamlit"] = _StreamlitShim()
for mod in ("workflow_sidebar", "page_transfers", "page_state", "draft_strategy_intel", "draft_team_fit"):
    __import__(mod)

import projection_calibration as proj_cal  # noqa: E402
from projection_style import get_draft_projection_factors  # noqa: E402
from projection_validation import ML_PROJECTION_VALIDATION_GROUPS  # noqa: E402

import app_tutorial  # noqa: F401

SA = BASE / "streamlit_app.py"
_src = SA.read_text(encoding="utf-8").splitlines()
_ui = next(i for i, line in enumerate(_src) if "st.set_page_config" in line)
_def = next(i for i, line in enumerate(_src) if line.startswith("def fmt_int"))
_render = next(i for i, line in enumerate(_src) if line.startswith("_APP_RENDER_START"))
exec(compile("\n".join(_src[:_ui] + _src[_def:_render]), str(SA), "exec"), globals())


def _resolve(df, name):
    return globals()["_resolve_consistency_player_name"](df, name) or name


def _run_ml_pipeline():
    _, yearly_df, _ = globals()["load_data"]()
    market_df = globals()["load_fantasypros_market_data"]()
    ml_training_df, ml_feature_cols, ml_models, current_rows, base_pred_df = globals()["build_base_ml_predictions"](
        yearly_df, 3, 75, max_player_pool=300
    )
    pred_df, _, _ = globals()["apply_advanced_projection_adjustments"](
        base_pred_df,
        current_rows,
        ml_training_df,
        ml_feature_cols,
        globals()["ML_TARGET_STATS"],
        regression_strength=0.20,
        age_strength=0.50,
        comp_weight=0.10,
        k_neighbors=10,
        refresh_token=1,
    )
    anchor_ids = tuple(sorted(str(x) for x in pred_df["playerID"].astype(str).unique()))
    anchors = globals()["build_stabilized_projection_anchors"](yearly_df, anchor_ids, lookback=5)
    if not anchors.empty:
        pred_df = proj_cal.apply_ml_final_output_calibration(pred_df, anchors)
    enriched = globals()["_ml_enrich_predictions_for_storage"](pred_df, yearly_df, 3, "Balanced")
    return yearly_df, market_df, enriched


def main():
    print("=== ML Predictions UI logic check ===\n")
    yearly_df, market_df, stored_df = _run_ml_pipeline()
    print(f"Stored ML rows: {len(stored_df)}")

    # 1) Breakout presence
    print("\n## 1. Breakout players in ML pool")
    for name in ML_PROJECTION_VALIDATION_GROUPS["breakout"]:
        fn = _resolve(stored_df, name)
        if not fn:
            print(f"  FAIL missing: {name}")
            continue
        row = stored_df[stored_df["fullName"].astype(str) == fn].iloc[0]
        conf = row.get("Projection Confidence", "")
        print(
            f"  OK {fn}: HR={row.get('Predicted HR')} conf={conf} "
            f"({row.get('Projection Confidence Score')}) warn={str(row.get('Projection Warning', ''))[:50]}"
        )

    # 2-3) Position filter + sort (display-only)
    print("\n## 2-3. Position filter + sort (display-only, no pipeline)")
    sorts = [
        "Predicted HR",
        "Predicted RBI",
        "Predicted R",
        "Predicted OPS",
        "Expected Fantasy Value",
        "Projection Confidence Score",
    ]
    for pos in ("OF", "C", "1B", "SS"):
        view = globals()["_ml_apply_display_view"](stored_df, pos, "Predicted HR")
        top = view.iloc[0]["fullName"] if not view.empty else "—"
        print(f"  Position={pos}: {len(view)} rows, top HR={top}")

    for sort_col in sorts:
        if sort_col not in stored_df.columns and sort_col != "Expected Fantasy Value":
            print(f"  SKIP sort {sort_col} (column missing)")
            continue
        view = globals()["_ml_apply_display_view"](stored_df, "All positions", sort_col)
        if view.empty:
            print(f"  FAIL sort {sort_col}: empty")
        else:
            lead = view.iloc[0]
            val = lead.get(sort_col, lead.get("ML Fantasy Value"))
            print(f"  OK sort {sort_col}: leader={lead['fullName']} value={val}")

    # Pipeline should NOT run on filter change (code audit marker)
    print("  Code: _ml_execute_pipeline_if_needed returns False unless Generate or tuning sig changes")

    # 4) Elite stars
    print("\n## 4. Elite stars")
    lab_pool = globals()["build_draft_lab_player_pool"](yearly_df, market_df, draft_window=5)
    for name in ML_PROJECTION_VALIDATION_GROUPS["elite"]:
        fn = _resolve(stored_df, name)
        if not fn:
            print(f"  FAIL missing: {name}")
            continue
        ml = stored_df[stored_df["fullName"].astype(str) == fn].iloc[0]
        lab_name = _resolve(lab_pool, name)
        lab_hr = "—"
        if lab_name:
            lab_hr = lab_pool[lab_pool["fullName"].astype(str) == lab_name].iloc[0].get("proj_HR")
        ml_hr = ml.get("Predicted HR")
        pct = ""
        if pd.notna(lab_hr) and float(lab_hr) > 0:
            pct = f" ({(float(ml_hr) - float(lab_hr)) / float(lab_hr) * 100:+.0f}% vs Draft Lab)"
        print(
            f"  {fn}: ML HR={ml_hr} Draft={lab_hr}{pct} "
            f"EFV={ml.get('Expected Fantasy Value', ml.get('ML Fantasy Value'))} "
            f"conf={ml.get('Projection Confidence')}"
        )

    # 6) Cross-system sample
    print("\n## 6. Cross-system (Judge, Rice, Caminero)")
    for name in ("Aaron Judge", "Ben Rice", "Junior Caminero"):
        fn = _resolve(stored_df, name)
        if not fn:
            continue
        ml = stored_df[stored_df["fullName"].astype(str) == fn].iloc[0]
        lab_name = _resolve(lab_pool, name)
        lab = lab_pool[lab_pool["fullName"].astype(str) == lab_name].iloc[0] if lab_name else None
        bundle = globals()["assemble_projection_breakdown_bundle"](name)
        bd = bundle.get("snapshot", {}).get("projections", {})
        print(
            f"  {name}: ML HR={ml.get('Predicted HR')} | "
            f"Draft={lab.get('proj_HR') if lab is not None else '—'} | "
            f"Breakdown={bd.get('HR')}"
        )

    # 8) Transfer nav df
    print("\n## 8. Contextual transfer top-3 (OF, sort HR)")
    nav = globals()["_build_ml_nav_results_df"](stored_df, "OF", "Predicted HR")
    if nav is None or nav.empty:
        print("  FAIL: empty nav df")
    else:
        top3 = nav.head(3)["Player"].tolist()
        print(f"  Top 3 OF by HR: {top3}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
