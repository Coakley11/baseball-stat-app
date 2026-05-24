"""Profile ML prediction pipeline stages (headless). Run: python scripts/profile_ml_pipeline.py"""

from __future__ import annotations

import sys
import time
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
        self.session_state = types.SimpleNamespace()
        self.sidebar = types.SimpleNamespace()

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in ("cache_data", "cache_resource", "dialog", "fragment"):
            return lambda *a, **kwargs: (lambda fn: fn)
        if name in ("spinner", "expander"):
            return lambda *a, **k: types.SimpleNamespace(
                __enter__=lambda s: s, __exit__=lambda *a: None
            )
        if name == "columns":
            def _columns(spec):
                n = spec if isinstance(spec, int) else len(spec)
                return [types.SimpleNamespace(
                    __enter__=lambda s: s, __exit__=lambda *a: None
                )] * n
            return _columns
        return lambda *a, **k: None


sys.modules["streamlit"] = _StreamlitShim()
for mod_name in ("workflow_sidebar", "page_transfers", "page_state", "draft_strategy_intel", "draft_team_fit"):
    __import__(mod_name)

import projection_calibration as proj_cal  # noqa: E402
from projection_style import get_draft_projection_factors  # noqa: E402

import app_tutorial  # noqa: F401

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
    "app_tutorial": app_tutorial,
    "proj_cal": proj_cal,
    "get_draft_projection_factors": get_draft_projection_factors,
}
exec(compile(_exec_src, str(SA), "exec"), _g)
app = types.SimpleNamespace(**{k: v for k, v in _g.items() if not k.startswith("__")})


def _timed(label, fn):
    t0 = time.perf_counter()
    out = fn()
    sec = time.perf_counter() - t0
    print(f"  {label}: {sec:.2f}s")
    return out, sec


def main():
    print("Loading Lahman data…")
    _, yearly_df, _ = app.load_data()
    print(f"  rows={len(yearly_df):,}")

    lookback, min_games, max_players, min_ab = 3, 150, 150, 300
    refresh = 0
    year_sig = app._ml_year_pool_signature(yearly_df)

    print("\n=== Full base training ===")
    out, _ = _timed(
        "build_base_ml_predictions",
        lambda: app.build_base_ml_predictions(yearly_df, lookback, min_games, max_players, refresh),
    )
    base_pack = dict(
        zip(
            ["ml_training_df", "ml_feature_cols", "ml_models", "current_rows", "base_pred_df"],
            out,
        )
    )
    print(f"    training rows: {len(base_pack['ml_training_df']):,}")
    print(f"    companions: {len(app._ml_training_companion_rows(base_pack['ml_training_df'])):,}")

    print("\n=== Precompute ===")
    base_pack, s2 = _timed(
        "finalize",
        lambda: app._finalize_ml_base_pack(dict(base_pack), yearly_df, lookback, year_sig, refresh),
    )

    print("\n=== Tuning-fast scenarios ===")
    scenarios = [
        ("balanced", 0.20, 0.50, 0.10, 10),
        ("high_regression", 0.55, 0.50, 0.10, 10),
        ("high_age", 0.20, 1.00, 0.10, 10),
        ("high_similarity", 0.20, 0.50, 0.55, 25),
    ]
    tune_times = []
    for name, reg, age, comp, k in scenarios:
        status, sec = _timed(
            f"[{name}]",
            lambda reg=reg, age=age, comp=comp, k=k: app._run_ml_tuning_fast(
                yearly_source=yearly_df,
                ml_lookback=lookback,
                ml_min_ab=min_ab,
                base_pack=base_pack,
                effective_regression_strength=reg,
                effective_age_strength=age,
                effective_comp_weight=comp,
                k_neighbors=k,
                refresh_token=refresh,
            ),
        )
        tune_times.append(sec)
        if status.get("ok"):
            pred = status["pred_df"]
            print(f"      players={len(pred):,}  runtime={status.get('runtime_sec')}s")

    print("\n=== Star spot-check (balanced) ===")
    status = app._run_ml_tuning_fast(
        yearly_source=yearly_df,
        ml_lookback=lookback,
        ml_min_ab=min_ab,
        base_pack=base_pack,
        effective_regression_strength=0.20,
        effective_age_strength=0.50,
        effective_comp_weight=0.10,
        k_neighbors=10,
        refresh_token=refresh,
    )
    pred = status.get("pred_df", pd.DataFrame())
    for name in app.DRAFT_SCORING_CONSISTENCY_PLAYERS:
        sub = pred[pred["fullName"].astype(str).str.contains(name.split()[-1], case=False, na=False)]
        if sub.empty:
            print(f"  {name}: not in pool")
            continue
        row = sub.iloc[0]
        print(
            f"  {row.get('fullName')}: HR={row.get('Predicted HR')} "
            f"OPS={float(row.get('Predicted OPS', 0)):.3f} R={row.get('Predicted R')}"
        )

    if tune_times:
        print(f"\nTuning-fast avg: {sum(tune_times)/len(tune_times):.2f}s  max: {max(tune_times):.2f}s")


if __name__ == "__main__":
    main()
