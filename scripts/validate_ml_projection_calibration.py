"""
Offline validation: ML calibrated projections vs Draft Lab anchors.

Run from repo root: python scripts/validate_ml_projection_calibration.py
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

try:
    import sklearn  # noqa: F401
    _SKLEARN = True
except ImportError:
    _SKLEARN = False


class _StreamlitShim(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {}
        self.sidebar = types.SimpleNamespace()

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in ("cache_data", "cache_resource", "dialog"):
            return lambda *a, **kwargs: (lambda fn: fn)
        if name in ("spinner", "expander"):
            class _Ctx:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            return lambda *a, **k: _Ctx()
        if name == "columns":
            def _columns(spec):
                n = spec if isinstance(spec, int) else len(spec)
                return [types.SimpleNamespace()] * n
            return _columns
        return lambda *a, **k: None


sys.modules["streamlit"] = _StreamlitShim()
for mod_name in ("workflow_sidebar", "page_transfers", "page_state", "draft_strategy_intel", "draft_team_fit"):
    __import__(mod_name)
    sys.modules[mod_name] = sys.modules[mod_name]

import projection_calibration as proj_cal  # noqa: E402
from projection_style import get_draft_projection_factors  # noqa: E402

import app_tutorial  # noqa: E402

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
    "get_draft_projection_factors": get_draft_projection_factors,
    "SKLEARN_AVAILABLE": _SKLEARN,
    "proj_cal": proj_cal,
    "app_tutorial": app_tutorial,
}
exec(compile(_exec_src, str(SA), "exec"), _g, _g)

VALIDATION_PLAYERS = [
    "Shohei Ohtani",
    "Aaron Judge",
    "Juan Soto",
    "Bobby Witt Jr.",
    "Cal Raleigh",
    "Kyle Tucker",
    "Gunnar Henderson",
    "Ronald Acuña Jr.",
    "Elly De La Cruz",
    "Jackson Merrill",
    "Junior Caminero",
    "Justin Turner",
]

STAT_PAIRS = [
    ("HR", "Predicted HR", "proj_HR", 8),
    ("RBI", "Predicted RBI", "proj_RBI", 12),
    ("R", "Predicted R", "proj_R", 12),
    ("SB", "Predicted SB", "proj_SB", 8),
    ("AVG", "Predicted BA", "proj_BA", 0.025),
    ("OPS", "Predicted OPS", "proj_OPS", 0.08),
]


def compute_ml_fantasy_value(pred_df: pd.DataFrame) -> pd.Series:
    normalize_series = _g["normalize_series"]
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
            out += normalize_series(pd.to_numeric(pred_df[col], errors="coerce").fillna(0)) * w
    return normalize_series(out)


def compute_projection_realism_flags(ml_row, lab_row) -> dict:
    """Heuristic dev flags — suspicious if far from anchor or outside baseball norms."""
    flags = []
    hr = pd.to_numeric(ml_row.get("Predicted HR"), errors="coerce")
    ops = pd.to_numeric(ml_row.get("Predicted OPS"), errors="coerce")
    ba = pd.to_numeric(ml_row.get("Predicted BA"), errors="coerce")
    lab_hr = pd.to_numeric(lab_row.get("proj_HR"), errors="coerce")
    lab_ops = pd.to_numeric(lab_row.get("proj_OPS"), errors="coerce")
    elite = pd.to_numeric(ml_row.get("Elite Star Score"), errors="coerce")
    conf = pd.to_numeric(ml_row.get("Projection Confidence Score"), errors="coerce")
    very_lim = bool(ml_row.get("Very Limited Data", False))

    if pd.notna(hr) and hr > 58:
        flags.append("HR near/above hard cap")
    if pd.notna(ops) and ops > 1.08:
        flags.append("OPS very high")
    if pd.notna(ba) and (ba < 0.200 or ba > 0.340):
        flags.append("AVG out of band")
    if pd.notna(hr) and pd.notna(lab_hr) and lab_hr > 5:
        pct = abs(hr - lab_hr) / lab_hr
        if pct > 0.22:
            flags.append(f"HR {pct*100:.0f}% off Draft Lab")
    if pd.notna(ops) and pd.notna(lab_ops) and lab_ops > 0.05:
        pct = abs(ops - lab_ops) / lab_ops
        if pct > 0.12:
            flags.append(f"OPS {pct*100:.0f}% off Draft Lab")
    if very_lim and pd.notna(hr) and pd.notna(lab_hr) and hr > lab_hr * 1.08:
        flags.append("small-sample still above anchor")
    if pd.notna(elite) and elite >= 0.72 and pd.notna(hr) and pd.notna(lab_hr) and hr < lab_hr * 0.88:
        flags.append("elite star may be too conservative")
    if pd.notna(conf) and conf < 0.40 and pd.notna(hr) and pd.notna(lab_hr) and abs(hr - lab_hr) < 1.5:
        flags.append("ML≈anchor (low individuality)")

    score = max(0.0, 1.0 - 0.15 * len(flags))
    return {"Realism Score": round(score, 3), "Flags": "; ".join(flags) if flags else "OK"}


def run_ml_pipeline(yearly_df, *, lookback=3, min_games=150, max_players=300, min_ab=300):
    build_base_ml_predictions = _g["build_base_ml_predictions"]
    apply_advanced_projection_adjustments = _g["apply_advanced_projection_adjustments"]
    build_stabilized_projection_anchors = _g["build_stabilized_projection_anchors"]
    ML_TARGET_STATS = _g["ML_TARGET_STATS"]

    ml_training_df, ml_feature_cols, ml_models, current_rows, base_pred_df = build_base_ml_predictions(
        yearly_df, lookback, min_games, max_player_pool=max_players
    )
    if base_pred_df.empty:
        raise RuntimeError("No base ML predictions")

    ab_ok = pd.to_numeric(base_pred_df["hist_AB_total"], errors="coerce").fillna(0) >= min_ab
    pred_df = base_pred_df.loc[ab_ok].reset_index(drop=True)
    pids = set(pred_df["playerID"].astype(str))
    cur_f = current_rows[current_rows["playerID"].astype(str).isin(pids)].reset_index(drop=True)

    pred_df, _, _ = apply_advanced_projection_adjustments(
        pred_df,
        cur_f,
        ml_training_df,
        ml_feature_cols,
        ML_TARGET_STATS,
        regression_strength=0.35,
        age_strength=0.50,
        comp_weight=0.10,
        k_neighbors=10,
        refresh_token=1,
    )
    anchor_ids = tuple(sorted(str(x) for x in pred_df["playerID"].unique()))
    anchors = build_stabilized_projection_anchors(yearly_df, anchor_ids, int(lookback))
    if not anchors.empty:
        pred_df = proj_cal.apply_ml_final_output_calibration(pred_df, anchors)
    pred_df["ML Fantasy Value"] = compute_ml_fantasy_value(pred_df)
    return pred_df, ml_models


def main() -> int:
    if not _SKLEARN:
        print("ERROR: scikit-learn required")
        return 1

    load_data = _g["load_data"]
    load_fantasypros_market_data = _g["load_fantasypros_market_data"]
    build_draft_lab_player_pool = _g["build_draft_lab_player_pool"]
    _resolve = _g["_resolve_consistency_player_name"]

    print("Loading data...")
    _bat, yearly_df, _people = load_data()
    market_df = load_fantasypros_market_data()

    print("Running ML pipeline (lookback=3, min AB=300)...")
    pred_df, models = run_ml_pipeline(yearly_df)
    print(f"  {len(pred_df)} players, {len(models)} models trained")

    lab_pool = build_draft_lab_player_pool(
        yearly_df, market_df, draft_window=3, fantasy_format="5x5 Roto", projection_style="Balanced"
    )

    print("\n=== Player validation (ML vs Draft Lab) ===\n")
    issues = []
    for pname in VALIDATION_PLAYERS:
        ml_name = _resolve(pred_df, pname)
        lab_name = _resolve(lab_pool, pname)
        if not ml_name:
            print(f"## {pname}\n  NOT IN ML POOL (try lower min AB)\n")
            continue
        if not lab_name:
            print(f"## {pname}\n  NOT IN DRAFT LAB POOL\n")
            continue
        ml_row = pred_df[pred_df["fullName"].astype(str) == ml_name].iloc[0]
        lab_row = lab_pool[lab_pool["fullName"].astype(str) == lab_name].iloc[0]
        flags = compute_projection_realism_flags(ml_row, lab_row)

        print(f"## {ml_name}")
        print(
            f"  Conf: {ml_row.get('Projection Confidence')} ({float(ml_row.get('Projection Confidence Score', 0)):.3f}) | "
            f"Elite: {float(ml_row.get('Elite Star Score', 0)):.3f} | Warning: {ml_row.get('Projection Warning', '')}"
        )
        print(
            f"  ML EFV: {float(ml_row.get('ML Fantasy Value', 0)):.4f} | "
            f"Lab EFV: {float(lab_row.get('Expected Fantasy Value', 0)):.4f} | "
            f"Realism: {flags['Realism Score']} - {flags['Flags']}"
        )
        for label, ml_col, lab_col, tol in STAT_PAIRS:
            mv = pd.to_numeric(ml_row.get(ml_col), errors="coerce")
            lv = pd.to_numeric(lab_row.get(lab_col), errors="coerce")
            diff = mv - lv if pd.notna(mv) and pd.notna(lv) else np.nan
            pct = (diff / lv * 100) if pd.notna(diff) and pd.notna(lv) and abs(float(lv)) > 1e-9 else np.nan
            flag = " !" if pd.notna(diff) and abs(diff) > tol else ""
            fmt = ".3f" if label in ("AVG", "OPS") else ".1f"
            print(
                f"  {label:4} ML={mv:{fmt}} Lab={lv:{fmt}} diff={diff:{fmt}} ({pct:+.1f}%){flag}"
                if pd.notna(pct)
                else f"  {label:4} ML={mv} Lab={lv}"
            )
        if flags["Flags"] != "OK":
            issues.append((ml_name, flags["Flags"]))
        # ML should not be identical clone
        identical = all(
            pd.notna(pd.to_numeric(ml_row.get(m), errors="coerce"))
            and pd.notna(pd.to_numeric(lab_row.get(l), errors="coerce"))
            and abs(float(ml_row[m]) - float(lab_row[l])) < 0.01
            for _, m, l, _ in STAT_PAIRS[:4]
            if m in ml_row and l in lab_row
        )
        if identical:
            print("  NOTE: counting stats nearly identical to Draft Lab — check ML individuality")
        print()

    print("=== Summary ===")
    print(f"Players checked: {len(VALIDATION_PLAYERS)}")
    print(f"Issues flagged: {len(issues)}")
    for name, fl in issues:
        print(f"  - {name}: {fl}")

    return 0 if len(issues) <= 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
