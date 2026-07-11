#!/usr/bin/env python3
"""App-wide page performance baseline — cold/warm stubs for P0–P2 pages.

Run from repo root:
  python scripts/profile_app_pages_baseline.py

Uses lightweight session fixtures and existing perf namespaces where available.
Full Streamlit reruns are not simulated; this script measures import + prep helpers.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

P0_PAGES = (
    "Live Draft Room",
    "Draft Assistant Simulator",
    "Draft Room Simulator",
    "Draft Lab / Simulation",
)
P1_PAGES = (
    "Waiver Wire / Add-Drop Center",
    "Fantasy Lineup Assistant",
    "Fantasy Standings Tracker",
    "Trade Analyzer",
)
P2_PAGES = (
    "Historical Explorer",
    "Career Totals",
    "Hall of Fame Case Builder",
    "Relationship Finder",
)


def _timed(label: str, fn) -> float:
    t0 = time.perf_counter()
    try:
        fn()
    except Exception as exc:
        print(f"  {label}: ERROR {type(exc).__name__}: {exc}")
        return (time.perf_counter() - t0) * 1000.0
    return (time.perf_counter() - t0) * 1000.0


def profile_live_draft_setup() -> dict[str, float]:
    from scripts.profile_live_draft_setup_baseline import (
        _fresh_setup_session,
        simulate_page_load_prep,
        simulate_setting_change,
    )

    session = _fresh_setup_session()
    return {
        "page_prep_warm_ms": _timed("page_prep", lambda: simulate_page_load_prep(session)),
        "on_change_ms": _timed(
            "on_change",
            lambda: simulate_setting_change(session, field="live_draft_team_count", value=12),
        ),
    }


def profile_scatter_encoding() -> dict[str, float]:
    import pandas as pd
    from scatter_encoding import build_scatter_size_encoding

    class _Alt:
        class Scale:
            def __init__(self, **kw):
                pass

        class Legend:
            def __init__(self, **kw):
                pass

        class Size:
            def __init__(self, field, **kw):
                pass

    df = pd.DataFrame({"HR": list(range(100)), "isHallOfFamer": [False] * 100})
    times: dict[str, float] = {}
    times["hr_size_encode_ms"] = _timed(
        "hr_size",
        lambda: build_scatter_size_encoding(df, "HR", alt_module=_Alt),
    )
    times["hof_bool_size_encode_ms"] = _timed(
        "hof_bool",
        lambda: build_scatter_size_encoding(df, "isHallOfFamer", alt_module=_Alt),
    )
    return times


def profile_shared_draft_context() -> dict[str, float]:
    from shared_draft_context import prepare_shared_draft_context

    session = {"active_page": "Draft Assistant Simulator", "draft_window": 3}
    return {
        "shared_context_ms": _timed(
            "shared_context",
            lambda: prepare_shared_draft_context(session, active_page="Draft Assistant Simulator", force_mirror=True),
        ),
    }


def profile_lineup_assistant() -> dict[str, float]:
    from scripts.profile_lineup_assistant_baseline import profile_lineup

    return profile_lineup(warm=True)


def main() -> int:
    patches = [patch("page_perf_phases.dev_perf_enabled", return_value=True)]
    for p in patches:
        p.start()
    try:
        print("=== App-wide performance baseline ===\n")
        print("P0 Live Draft setup:")
        for k, v in profile_live_draft_setup().items():
            print(f"  {k}: {v:.1f} ms")

        print("\nP0 shared draft context:")
        for k, v in profile_shared_draft_context().items():
            print(f"  {k}: {v:.1f} ms")

        print("\nP2 scatter size encoding:")
        for k, v in profile_scatter_encoding().items():
            print(f"  {k}: {v:.1f} ms")

        print("\nP1 Fantasy Lineup Assistant (warm cached helpers):")
        for k, v in profile_lineup_assistant().items():
            print(f"  {k}: {v:.1f} ms")

        print("\nPages queued for full instrumentation:")
        for group, pages in (("P0", P0_PAGES), ("P1", P1_PAGES), ("P2", P2_PAGES)):
            print(f"  {group}: {', '.join(pages)}")

        print("\nSee docs/APP_WIDE_PERFORMANCE_SPRINT.md for ranked optimization plan.")
        return 0
    finally:
        for p in patches:
            p.stop()


if __name__ == "__main__":
    raise SystemExit(main())
