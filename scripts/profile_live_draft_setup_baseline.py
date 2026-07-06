#!/usr/bin/env python3
"""Profile Live Draft setup/configuration path (pre-room).

Run from repo root:
  python scripts/profile_live_draft_setup_baseline.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fresh_setup_session(*, with_sim_board: bool = True) -> dict:
    session: dict = {
        "_page_perf_ns": {"page": "Live Draft Room", "timings": {}, "started_at": time.perf_counter()},
        "active_page": "Live Draft Room",
        "main_sidebar_page": "Live Draft Room",
        "page_filter_state": {},
        "live_draft_setup_mode": "solo",
        "live_draft_room": None,
        "live_draft_league_name": "My Fantasy League",
        "live_draft_team_count": 10,
        "live_draft_picks_per_team": 15,
        "live_draft_type": "Snake Draft",
        "live_draft_scoring": "Roto (5x5)",
        "live_draft_timer": "60 seconds",
        "live_draft_auto_rule": "Balanced recommendation",
        "live_draft_proj_style": "Balanced",
        "live_draft_proj_window": 3,
        "live_slot_c": 1,
        "live_slot_1b": 1,
        "live_slot_2b": 1,
        "live_slot_3b": 1,
        "live_slot_ss": 1,
        "live_slot_of": 3,
        "live_slot_dh": 1,
        "live_slot_p": 5,
        "live_slot_bench": 3,
        "room_format": "5x5 Roto",
        "room_your_team": "Daniel",
        "room_window": 3,
        "fantasy_draft_projection_style": "Balanced",
        "draft_use_ml_blend": True,
        "draft_ml_blend_weight": 0.12,
    }
    if with_sim_board:
        try:
            import pandas as pd
            from draft_room_state import DRAFT_ROOM_TABLE_KEY, write_canonical_draft_room_state

            teams = [f"Team {i}" for i in range(1, 11)]
            rows = []
            pick = 1
            for rnd in range(1, 4):
                for team in teams:
                    rows.append(
                        {
                            "Pick": pick,
                            "Round": rnd,
                            "Fantasy Team": team,
                            "Player": "",
                            "Primary Position": "",
                        }
                    )
                    pick += 1
            board = pd.DataFrame(rows)
            session[DRAFT_ROOM_TABLE_KEY] = board
            write_canonical_draft_room_state(session, board, reason="setup_profile_fixture", local_edit=False)
        except ImportError:
            pass
    return session


def _mock_st(session: dict) -> MagicMock:
    st = MagicMock()
    st.session_state = session
    return st


def simulate_page_load_prep(session: dict) -> float:
    """Mirror global + Live Draft page prep before widgets render."""
    t0 = time.perf_counter()
    try:
        from global_fantasy_settings_state import GLOBAL_FORMAT_KEY, prepare_global_fantasy_settings, to_live_draft_scoring
        from shared_draft_context import prepare_shared_draft_context
        from draft_room_state import ensure_live_draft_synced_to_canonical_board, prepare_draft_room_state
        from live_draft_state import prepare_live_draft_state
        from live_draft_setup_persist import should_skip_draft_room_prep_for_live_setup, should_skip_live_draft_state_prep

        prepare_global_fantasy_settings(session, force_mirror=True)
        fmt = session.get(GLOBAL_FORMAT_KEY)
        if fmt is not None:
            session["live_draft_scoring"] = to_live_draft_scoring(fmt)
        prepare_shared_draft_context(session, active_page="Live Draft Room", force_mirror=True)
        if not should_skip_draft_room_prep_for_live_setup(session):
            ensure_live_draft_synced_to_canonical_board(session, reason="setup_profile")
            prepare_draft_room_state(session)
        if not should_skip_live_draft_state_prep(session):
            prepare_live_draft_state(session)
    except ImportError as exc:
        print(f"  prep import failed: {exc}")
    return (time.perf_counter() - t0) * 1000.0


def simulate_setting_change(session: dict, *, field: str, value: object) -> float:
    """Lightweight setup widget on_change (deferred persist)."""
    session[field] = value
    t0 = time.perf_counter()
    try:
        from live_draft_setup_persist import on_live_draft_setup_widget_changed

        on_live_draft_setup_widget_changed(session)
    except ImportError as exc:
        print(f"  on_change import failed: {exc}")
    return (time.perf_counter() - t0) * 1000.0


def simulate_setup_flush(session: dict, st: MagicMock) -> float:
    t0 = time.perf_counter()
    try:
        from live_draft_setup_persist import flush_live_draft_setup_persist

        flush_live_draft_setup_persist(st, session, reason="live_draft_setup_profile_flush")
    except ImportError as exc:
        print(f"  flush import failed: {exc}")
    return (time.perf_counter() - t0) * 1000.0


def _print_phases(session: dict, *, title: str) -> None:
    from live_draft_perf import setup_phase_total_ms, summarize_setup_phases

    phases = summarize_setup_phases(session, limit=20)
    print(f"\n{title}")
    print(f"  instrumented setup total: {setup_phase_total_ms(session):.1f} ms")
    for name, ms in phases:
        bar = "#" * min(40, int(ms / 25))
        print(f"  {name:42} {ms:8.1f} ms  {bar}")


def main() -> int:
    patches = [
        patch("page_perf_phases.dev_perf_enabled", return_value=True),
        patch("suite_user_persistence.force_autosave", return_value=True),
    ]
    for p in patches:
        p.start()

    try:
        print("=== Live Draft setup profile (deferred persist, room=None) ===\n")

        # Warm imports
        session = _fresh_setup_session(with_sim_board=True)
        simulate_page_load_prep(session)

        session = _fresh_setup_session(with_sim_board=True)
        st = _mock_st(session)
        prep_ms = simulate_page_load_prep(session)
        print(f"Page-load prep wall (warm): {prep_ms:.1f} ms")
        _print_phases(session, title="After page-load prep")

        changes = [
            ("live_draft_team_count", 12),
            ("live_draft_scoring", "Points League"),
            ("live_slot_of", 4),
            ("live_draft_proj_window", 5),
        ]
        onchange_walls: list[float] = []
        for field, value in changes:
            session = _fresh_setup_session(with_sim_board=True)
            st = _mock_st(session)
            simulate_page_load_prep(session)
            wall = simulate_setting_change(session, field=field, value=value)
            onchange_walls.append(wall)
            print(f"\nSetting change {field}={value!r}: wall {wall:.1f} ms (dirty={session.get('_live_draft_setup_dirty')})")
            _print_phases(session, title=f"Phases for {field} on_change")

        session = _fresh_setup_session(with_sim_board=True)
        st = _mock_st(session)
        simulate_page_load_prep(session)
        simulate_setting_change(session, field="live_draft_team_count", value=12)
        flush_ms = simulate_setup_flush(session, st)
        print(f"\nExplicit flush after team_count change: wall {flush_ms:.1f} ms")
        _print_phases(session, title="Phases for explicit flush")

        print("\n=== Summary ===")
        print(f"  on_change wall (max): {max(onchange_walls):.1f} ms")
        print(f"  explicit flush wall: {flush_ms:.1f} ms")
        print("  Targets: on_change <500 ms, flush may be slower (disk/cloud)")
        ok = max(onchange_walls) < 500.0
        print(f"\n{'PASS' if ok else 'FAIL'}: setup on_change under 500 ms")
        return 0 if ok else 1
    finally:
        for p in patches:
            p.stop()


if __name__ == "__main__":
    raise SystemExit(main())
