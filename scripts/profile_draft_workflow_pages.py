#!/usr/bin/env python3
"""Draft workflow page performance baseline — cold/warm phase timings.

Run from repo root:
  python scripts/profile_draft_workflow_pages.py
  python scripts/profile_draft_workflow_pages.py --json docs/PERFORMANCE_DRAFT_WORKFLOW_BASELINE.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TARGET_PAGES = (
    "Live Draft Room",
    "Draft Assistant Simulator",
    "Saved Draft Library",
    "Draft Room Simulator",
    "Fantasy Lineup Assistant",
    "Fantasy Standings Tracker",
    "Waiver Wire / Add-Drop Center",
)


def _timed(label: str, fn: Callable[[], Any]) -> tuple[float, Any]:
    t0 = time.perf_counter()
    try:
        out = fn()
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000.0
        return elapsed, {"error": f"{type(exc).__name__}: {exc}"}
    return (time.perf_counter() - t0) * 1000.0, out


def _fresh_session() -> dict[str, Any]:
    return {
        "active_page": "Draft Assistant Simulator",
        "draft_window": 3,
        "_lahman_max_year": 2024,
        "fantasy_league_context_state": {"contexts": {}, "active_league_context_id": ""},
    }


def profile_workflow_descriptor(session: dict[str, Any]) -> dict[str, float]:
    from fantasy_context_source import resolve_fantasy_workflow_source_descriptor

    cold_ms, _ = _timed("workflow_descriptor_cold", lambda: resolve_fantasy_workflow_source_descriptor(session))
    warm_ms, _ = _timed("workflow_descriptor_warm", lambda: resolve_fantasy_workflow_source_descriptor(session))
    return {"cold_ms": round(cold_ms, 2), "warm_ms": round(warm_ms, 2)}


def profile_library_selection(session: dict[str, Any]) -> dict[str, float]:
    from saved_draft_library_selection import prepare_saved_draft_library_active_selection

    cold_ms, _ = _timed("library_selection_cold", lambda: prepare_saved_draft_library_active_selection(session))
    warm_ms, _ = _timed("library_selection_warm", lambda: prepare_saved_draft_library_active_selection(session))
    return {"cold_ms": round(cold_ms, 2), "warm_ms": round(warm_ms, 2)}


def profile_live_draft_room() -> dict[str, Any]:
    from scripts.profile_live_draft_baseline import main as live_main

    # Reuse existing live draft profiler internals
    import scripts.profile_live_draft_baseline as ldb

    room = ldb._sample_room()
    session: dict[str, Any] = {"live_draft_room": room, "_page_perf_ns": {"timings": {}}}
    out: dict[str, Any] = {}
    out["available_pool_cold_ms"], _ = _timed(
        "available_pool_cold",
        lambda: ldb.cached_live_draft_get_available(session, room) if hasattr(ldb, "cached_live_draft_get_available") else None,
    )
    try:
        from live_draft_ui_cache import cached_live_draft_get_available

        out["available_pool_cold_ms"], _ = _timed(
            "available_pool_cold",
            lambda: cached_live_draft_get_available(session, room),
        )
        out["available_pool_warm_ms"], _ = _timed(
            "available_pool_warm",
            lambda: cached_live_draft_get_available(session, room),
        )
    except ImportError:
        pass
    try:
        from live_draft_recommendations import cached_live_draft_recommendations

        out["recommendations_cold_ms"], _ = _timed(
            "recommendations_cold",
            lambda: cached_live_draft_recommendations(session, room, top_n=10),
        )
        out["recommendations_warm_ms"], _ = _timed(
            "recommendations_warm",
            lambda: cached_live_draft_recommendations(session, room, top_n=10),
        )
    except ImportError:
        pass
    return {k: round(float(v), 2) for k, v in out.items() if isinstance(v, (int, float))}


def profile_draft_assistant(session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        from draft_assistant_board import resolve_draft_assistant_board

        out["board_resolve_cold_ms"], _ = _timed("board_resolve_cold", lambda: resolve_draft_assistant_board(session))
        out["board_resolve_warm_ms"], _ = _timed("board_resolve_warm", lambda: resolve_draft_assistant_board(session))
    except ImportError:
        pass
    try:
        from shared_draft_context import prepare_shared_draft_context

        out["shared_context_ms"], _ = _timed(
            "shared_context",
            lambda: prepare_shared_draft_context(session, active_page="Draft Assistant Simulator", force_mirror=True),
        )
    except ImportError:
        pass
    return {k: round(float(v), 2) for k, v in out.items()}


def profile_fantasy_standings(session: dict[str, Any]) -> dict[str, float]:
    try:
        from fantasy_state import prepare_fantasy_standings_page

        cold_ms, _ = _timed("standings_prep_cold", lambda: prepare_fantasy_standings_page(session))
        warm_ms, _ = _timed("standings_prep_warm", lambda: prepare_fantasy_standings_page(session))
        return {"cold_ms": round(cold_ms, 2), "warm_ms": round(warm_ms, 2)}
    except ImportError:
        return {}


def profile_lineup(session: dict[str, Any]) -> dict[str, float]:
    try:
        from scripts.profile_lineup_assistant_baseline import profile_lineup

        result = profile_lineup(warm=True)
        return {k: round(float(v), 2) for k, v in result.items() if isinstance(v, (int, float))}
    except ImportError:
        return {}


def run_baseline() -> dict[str, Any]:
    from draft_archive_state import DRAFT_ARCHIVE_KEY

    session = _fresh_session()
    session[DRAFT_ARCHIVE_KEY] = []
    report: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pages": {},
        "shared": {},
    }
    with patch("page_perf_phases.dev_perf_enabled", return_value=True):
        report["shared"]["workflow_descriptor"] = profile_workflow_descriptor(session)
        report["shared"]["library_selection"] = profile_library_selection(session)
        report["pages"]["Live Draft Room"] = profile_live_draft_room()
        report["pages"]["Draft Assistant Simulator"] = profile_draft_assistant(session)
        report["pages"]["Saved Draft Library"] = profile_library_selection(session)
        report["pages"]["Draft Room Simulator"] = profile_workflow_descriptor(session)
        report["pages"]["Fantasy Standings Tracker"] = profile_fantasy_standings(session)
        report["pages"]["Fantasy Lineup Assistant"] = profile_lineup(session)
        report["pages"]["Waiver Wire / Add-Drop Center"] = profile_workflow_descriptor(session)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile draft workflow pages")
    parser.add_argument("--json", type=str, default="", help="Write JSON report to path")
    args = parser.parse_args()
    report = run_baseline()
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
