"""
Offline verification of shared draft scoring across page pipelines.

Run from repo root: python scripts/verify_draft_scoring_consistency.py
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
        if name in ("cache_data", "cache_resource", "dialog"):
            return lambda *a, **kwargs: (lambda fn: fn)
        if name == "spinner":
            return lambda *a, **k: types.SimpleNamespace(
                __enter__=lambda s: s, __exit__=lambda *a: None
            )
        if name == "expander":
            return lambda *a, **k: types.SimpleNamespace(
                __enter__=lambda s: s, __exit__=lambda *a: None
            )
        if name == "columns":
            return lambda n: [types.SimpleNamespace()] * n
        return lambda *a, **k: None


sys.modules["streamlit"] = _StreamlitShim()
for mod_name, mod_path in (
    ("workflow_sidebar", "workflow_sidebar"),
    ("page_transfers", "page_transfers"),
    ("page_state", "page_state"),
    ("draft_strategy_intel", "draft_strategy_intel"),
    ("draft_team_fit", "draft_team_fit"),
):
    __import__(mod_path)
    sys.modules[mod_name] = sys.modules[mod_path]

from projection_style import PROJECTION_STYLE_OPTIONS, get_draft_projection_factors  # noqa: E402

_app_src = SA.read_text(encoding="utf-8").splitlines()
# Load only definitions (stop before main app render / sidebar).
_cut = next(i for i, line in enumerate(_app_src) if line.startswith("_APP_RENDER_START"))
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
    "PROJECTION_STYLE_OPTIONS": PROJECTION_STYLE_OPTIONS,
    "get_draft_projection_factors": get_draft_projection_factors,
    "SKLEARN_AVAILABLE": False,
}
exec(compile("\n".join(_app_src[:_cut]), str(SA), "exec"), _g, _g)


def main() -> int:
    load_data = _g["load_data"]
    load_fantasypros_market_data = _g["load_fantasypros_market_data"]
    build_unified_draft_player_pool = _g["build_unified_draft_player_pool"]
    run_draft_scoring_consistency_check = _g["run_draft_scoring_consistency_check"]
    _resolve_consistency_player_name = _g["_resolve_consistency_player_name"]
    DRAFT_SCORING_CONSISTENCY_PLAYERS = _g["DRAFT_SCORING_CONSISTENCY_PLAYERS"]

    print("Loading Lahman + market data...")
    _bat, yearly_df, _people = load_data()
    market_df = load_fantasypros_market_data()
    if market_df.empty:
        print("WARNING: No FantasyPros market data — Market Rank / Edge may be NaN.")

    settings = dict(
        draft_window=3,
        fantasy_format="5x5 Roto",
        projection_style="Balanced",
        use_ml_blend=True,
        ml_blend_weight=0.12,
        ml_min_games_for_signal=50,
    )

    print("\nRunning consistency check...")
    summary, notes = run_draft_scoring_consistency_check(
        yearly_df,
        market_df,
        test_players=DRAFT_SCORING_CONSISTENCY_PLAYERS,
        **settings,
    )

    pool = build_unified_draft_player_pool(yearly_df, market_df, **settings)
    print("\n=== Pool-level snapshot (canonical unified pool) ===")
    for pname in DRAFT_SCORING_CONSISTENCY_PLAYERS:
        resolved = _resolve_consistency_player_name(pool, pname)
        if not resolved:
            print(f"  {pname}: NOT IN POOL")
            continue
        r = pool[pool["fullName"].astype(str) == resolved].iloc[0]
        efv = pd.to_numeric(r.get("Expected Fantasy Value"), errors="coerce")
        print(
            f"  {resolved}: HR={r.get('proj_HR')} RBI={r.get('proj_RBI')} R={r.get('proj_R')} "
            f"SB={r.get('proj_SB')} BA={float(r.get('proj_BA', 0)):.3f} OPS={float(r.get('proj_OPS', 0)):.3f} "
            f"EFV={efv:.4f} MR={r.get('Market Rank')} MdlR={r.get('Model Rank')} Edge={r.get('Fantasy Edge')} "
            f"Slp={float(r.get('Sleeper Score', 0)):.4f} Scarc={float(r.get('Scarcity Score', 0)):.4f} "
            f"Conf={r.get('Projection Confidence Score')}"
        )

    print("\n=== Match status summary ===")
    for status, n in summary["Match Status"].value_counts().items():
        print(f"  {str(status).encode('ascii', 'replace').decode()}: {n}")
    if notes:
        print("\nDetail notes:")
        for line in notes[:10]:
            print(f"  - {line}")

    mismatches = summary[summary["Match Status"].astype(str).str.contains("Mismatch", na=False)]
    pool_sources = summary[summary["Page / Source"].astype(str).str.contains("canonical pool", na=False)]
    pool_ok = (pool_sources["Match Status"] == "✅ Match").all() if not pool_sources.empty else False

    print("\n=== Verdict ===")
    if pool_ok and mismatches.empty:
        print("PASS: Pool metrics match on all canonical sources.")
        return 0
    if pool_ok:
        print("PASS (pool): Canonical pool matches. Context-only rows are expected.")
        return 0
    print("FAIL: Pool mismatches.")
    if not mismatches.empty:
        print(mismatches[["Player", "Page / Source", "Match Status", "Notes"]].head(20).to_string(index=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
