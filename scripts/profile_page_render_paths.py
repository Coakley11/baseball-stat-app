"""Profile full-page render phases (script path — complements Streamlit wall-clock timing)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TARGET_PAGES = (
    "Saved Draft Library",
    "Fantasy Lineup Assistant",
    "Fantasy Standings Tracker",
    "Waiver Wire / Add-Drop Center",
    "Live Draft Room",
    "Draft Assistant Simulator",
)


def _empty_session() -> dict:
    return {
        "draft_archive_teams": [],
        "fantasy_league_context_state": {"contexts": {}, "active_league_context_id": ""},
        "_suite_auth_user_id": "profile_script",
        "_suite_active_workspace_id": "daniel",
    }


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 2)


def profile_page_paths(session: dict) -> dict:
    report: dict = {"pages": {}, "shared": {}}

    t0 = time.perf_counter()
    try:
        from draft_library_manifest import build_library_manifest

        build_library_manifest(session)
        report["pages"]["Saved Draft Library"] = {"manifest_ms": _ms(t0)}
    except ImportError:
        report["pages"]["Saved Draft Library"] = {"error": "manifest_import"}

    t0 = time.perf_counter()
    try:
        from library_repair_scheduler import run_gated_library_repairs

        trace = run_gated_library_repairs(session, user_mutated=False)
        report["pages"]["Saved Draft Library"]["repair_first_ms"] = _ms(t0)
        t1 = time.perf_counter()
        trace2 = run_gated_library_repairs(session, user_mutated=False)
        report["pages"]["Saved Draft Library"]["repair_repeat_ms"] = _ms(t1)
        report["pages"]["Saved Draft Library"]["repair_trace"] = trace
        report["pages"]["Saved Draft Library"]["repair_repeat_skipped"] = trace2.get("skipped")
    except ImportError:
        pass

    t0 = time.perf_counter()
    try:
        from saved_draft_library_selection import prepare_saved_draft_library_active_selection

        prepare_saved_draft_library_active_selection(session)
        report["shared"]["library_selection_cold_ms"] = _ms(t0)
        t1 = time.perf_counter()
        prepare_saved_draft_library_active_selection(session)
        report["shared"]["library_selection_warm_ms"] = _ms(t1)
    except ImportError:
        pass

    t0 = time.perf_counter()
    try:
        from fantasy_context_source import resolve_fantasy_workflow_source_descriptor

        resolve_fantasy_workflow_source_descriptor(session)
        report["shared"]["workflow_descriptor_cold_ms"] = _ms(t0)
        t1 = time.perf_counter()
        resolve_fantasy_workflow_source_descriptor(session)
        report["shared"]["workflow_descriptor_warm_ms"] = _ms(t1)
    except ImportError:
        pass

    t0 = time.perf_counter()
    try:
        from live_draft_lineup_config import repair_known_live_draft_lineup_configs

        repair_known_live_draft_lineup_configs(session)
        report["pages"]["Fantasy Lineup Assistant"] = {"lineup_repair_ms": _ms(t0)}
    except ImportError:
        pass

    for page in TARGET_PAGES:
        report["pages"].setdefault(page, {})

    report["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=str, default="")
    args = parser.parse_args()
    session = _empty_session()
    report = profile_page_paths(session)
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        out = Path(args.json)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
