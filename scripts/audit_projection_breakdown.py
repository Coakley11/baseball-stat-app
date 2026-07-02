#!/usr/bin/env python3
"""Audit Projection Breakdown: cross-page consistency, elite realism, trend caps.

Run from repo root: python scripts/audit_projection_breakdown.py
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
            return lambda *a, **k: types.SimpleNamespace(
                __enter__=lambda s: s, __exit__=lambda *a: None
            )
        return lambda *a, **k: None


sys.modules["streamlit"] = _StreamlitShim()
for mod_name in ("workflow_sidebar", "page_transfers", "page_state", "draft_strategy_intel", "draft_team_fit"):
    __import__(mod_name)

import projection_breakdown as proj_bd  # noqa: E402
from projection_style import get_draft_projection_factors  # noqa: E402
import projection_calibration as proj_cal  # noqa: E402
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

ELITE = [
    "Shohei Ohtani",
    "Aaron Judge",
    "Juan Soto",
    "Bobby Witt Jr.",
    "Gunnar Henderson",
    "Cal Raleigh",
    "Kyle Tucker",
]

# Rough MLB star sanity bands for stabilized 3-year window (not strict pass/fail).
ELITE_HR_BAND = (18, 55)
ELITE_OPS_BAND = (0.780, 1.050)


def _simulate_page_opens(app, name: str) -> list[dict]:
    """Same player, different fake page contexts — projections must match."""
    legacy_row = pd.Series({
        "fullName": name,
        "proj_HR": 99.0,
        "proj_OPS": 1.500,
        "HR_trend": 50.0,
    })
    bundles = []
    for _label in ("draft_assistant", "trends", "comparison", "sleepers", "historical"):
        b = app.assemble_projection_breakdown_bundle(
            name,
            pool_row=legacy_row,
            projection_lookup_df=pd.DataFrame([legacy_row]),
            projection_lookup_name_col="fullName",
        )
        bundles.append(b)
    return bundles


def main() -> int:
    app = _g
    if app.get("yearly_df") is None or app["yearly_df"].empty:
        print("SKIP: yearly_df not loaded.")
        return 0

    pool = app["get_projection_breakdown_pool_live"]()
    print(f"Breakdown pool: {len(pool)} players | settings={app['_draft_projection_session_kwargs']()}")
    print()

    issues = 0

    # Cross-page consistency
    print("=== Cross-page consistency (same player, legacy page rows ignored) ===")
    for name in ELITE[:3]:
        bundles = _simulate_page_opens(app, name)
        hrs = [b.get("snapshot", {}).get("projections", {}).get("HR") for b in bundles]
        if len(set(hrs)) > 1:
            print(f"FAIL {name}: HR differs across simulated pages: {hrs}")
            issues += 1
        elif all(h is not None for h in hrs):
            print(f"OK   {name}: HR={hrs[0]} on all simulated page opens")
        else:
            print(f"WARN {name}: missing HR in bundle")
    print()

    # Elite realism
    print("=== Elite player realism ===")
    for name in ELITE:
        b = app["assemble_projection_breakdown_bundle"](name)
        if not b.get("stabilized"):
            print(f"WARN {name}: not stabilized ({b.get('data_source')})")
            continue
        snap = b["snapshot"]["projections"]
        hr = snap.get("HR")
        ops = snap.get("OPS")
        conf = b["snapshot"].get("confidence_label", "")
        warn = b["snapshot"].get("warning", "")
        ok = True
        if hr is None or not (ELITE_HR_BAND[0] <= hr <= ELITE_HR_BAND[1]):
            print(f"CHECK {name}: HR={hr} outside band {ELITE_HR_BAND}")
            ok = False
        if ops is None or not (ELITE_OPS_BAND[0] <= ops <= ELITE_OPS_BAND[1]):
            print(f"CHECK {name}: OPS={ops:.3f} outside band {ELITE_OPS_BAND}")
            ok = False
        if ok:
            print(f"OK   {name}: HR={hr:.0f} OPS={ops:.3f} conf={conf!r} warn={warn[:40]!r}")
    print()

    # Trend caps
    print("=== Trend display caps ===")
    absurd = pd.DataFrame({
        "yearID": [2023, 2024, 2025],
        "G": [150, 150, 150],
        "HR": [10, 20, 60],
    })
    slopes, n = proj_bd.compute_display_trends_from_seasons(absurd)
    hr_slope = slopes.get("HR_trend")
    if hr_slope is not None and abs(hr_slope) <= proj_bd.DISPLAY_COUNT_SLOPE_CAP:
        print(f"OK   HR spike slope capped for display: {hr_slope}")
    else:
        print(f"FAIL HR slope not capped: {hr_slope}")
        issues += 1
    print()

    print(f"Audit finished with {issues} issue(s).")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
