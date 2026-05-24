#!/usr/bin/env python3
"""Compare Projection Breakdown resolved rows vs Draft Lab pool for named stars.

Run from repo root: python scripts/verify_projection_breakdown_consistency.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Minimal Streamlit stub so streamlit_app imports without running the UI.
import types

st = types.SimpleNamespace()
st.session_state = {}
st.cache_data = lambda **kw: (lambda fn: fn)
st.dialog = lambda *a, **k: (lambda fn: fn)
st.sidebar = types.SimpleNamespace()
sys.modules["streamlit"] = st

import projection_breakdown as proj_bd  # noqa: E402

PLAYERS = [
    "Shohei Ohtani",
    "Aaron Judge",
    "Juan Soto",
    "Bobby Witt Jr.",
    "Gunnar Henderson",
    "Cal Raleigh",
    "Kyle Tucker",
]


def main():
    import streamlit_app as app  # noqa: WPS433

    if getattr(app, "yearly_df", None) is None or app.yearly_df.empty:
        print("SKIP: yearly_df not loaded — run inside full app environment.")
        return 0

    pool = app.get_cached_unified_projection_pool_live()
    print(f"Unified pool rows: {len(pool)}")
    print(f"Window/style: {app._draft_projection_session_kwargs()}")
    print()

    for name in PLAYERS:
        canonical = app._resolve_consistency_player_name(pool, name) or name
        lab_row = pool[pool["fullName"].astype(str).str.strip() == str(canonical).strip()]
        if lab_row.empty:
            print(f"{name}: NOT IN POOL")
            continue
        lab = lab_row.iloc[0]
        bundle = app.assemble_projection_breakdown_bundle(name)
        snap = bundle.get("snapshot", {}).get("projections", {})
        stabilized = bundle.get("stabilized")
        hr_lab = float(lab.get("proj_HR", float("nan")))
        hr_bd = snap.get("HR")
        ops_lab = float(lab.get("proj_OPS", float("nan")))
        ops_bd = snap.get("OPS")
        hr_ok = pd.notna(hr_lab) and hr_bd is not None and abs(hr_lab - hr_bd) < 0.05
        ops_ok = pd.notna(ops_lab) and ops_bd is not None and abs(ops_lab - ops_bd) < 0.002
        flag = "OK" if stabilized and hr_ok and ops_ok else "CHECK"
        print(
            f"{flag} {name}: stabilized={stabilized} "
            f"HR lab={hr_lab:.1f} breakdown={hr_bd} "
            f"OPS lab={ops_lab:.3f} breakdown={ops_bd:.3f} "
            f"conf={lab.get('Projection Confidence', '')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
