"""Trace save/restore cycle for draft settings + canonical format vs team.

Simulates the real Streamlit save -> refresh -> restore path using the actual
baseball_persistent_state functions, for the NO-PICKS settings scenario that
the user reports failing. Compares the canonical FORMAT path against the
working TEAM path to find where format diverges.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baseball_persistent_state import (
    apply_baseball_disk_state,
    build_baseball_disk_state,
)
from global_fantasy_settings_state import (
    FORMAT_ALIASES,
    GLOBAL_FORMAT_KEY,
    GLOBAL_TEAM_KEY,
    TEAM_ALIASES,
    on_alias_format_changed,
    on_alias_team_changed,
    prepare_global_fantasy_settings,
    mirror_canonical_to_all_aliases,
)


def _fmt_aliases(ss: dict) -> dict:
    return {a: ss.get(a) for a in FORMAT_ALIASES}


def _team_aliases(ss: dict) -> dict:
    return {a: ss.get(a) for a in TEAM_ALIASES}


def _snapshot(label: str, ss: dict) -> None:
    print(f"\n--- {label} ---")
    print(f"  canonical {GLOBAL_FORMAT_KEY!r:>14} = {ss.get(GLOBAL_FORMAT_KEY)!r}")
    print(f"  canonical {GLOBAL_TEAM_KEY!r:>14} = {ss.get(GLOBAL_TEAM_KEY)!r}")
    print(f"  format aliases: {_fmt_aliases(ss)}")
    print(f"  team   aliases: {_team_aliases(ss)}")
    dr = ss.get("draft_room_state")
    if isinstance(dr, dict):
        print(f"  blob draft_room_state.room_format = {dr.get('room_format')!r}")
        print(f"  blob draft_room_state.room_your_team = {dr.get('room_your_team')!r}")


def main() -> None:
    # ---------------------------------------------------------------
    # 1. Fresh session on Draft Room Simulator, NO picks drafted yet.
    #    Defaults seeded.
    # ---------------------------------------------------------------
    st = MagicMock()
    ss: dict = {
        "active_page": "Draft Room Simulator",
        "main_sidebar_page": "Draft Room Simulator",
        "room_your_team": "Team 1",
        "room_team_count": 4,
        "room_rounds": 3,
        "room_format": "5x5 Roto",
    }
    st.session_state = ss
    prepare_global_fantasy_settings(ss)
    _snapshot("1. Fresh session (defaults seeded)", ss)

    # ---------------------------------------------------------------
    # 2. User changes FORMAT to "Points League" and TEAM to "Team 2"
    #    via the canonical write path (what on_change handlers call).
    # ---------------------------------------------------------------
    ss["draft_format"] = "Points League"
    on_alias_format_changed(ss, "draft_format")
    ss["comparison_user_team"] = "Team 2"
    on_alias_team_changed(ss, "comparison_user_team")
    _snapshot("2. After user changes format=Points League, team=Team 2", ss)

    # ---------------------------------------------------------------
    # 3. SAVE: build the disk blob.
    # ---------------------------------------------------------------
    blob = build_baseball_disk_state(st)
    print("\n--- 3. SAVED BLOB top-level keys ---")
    print(f"  blob['room_format'] = {blob.get('room_format')!r}")
    print(f"  blob['room_your_team'] = {blob.get('room_your_team')!r}")
    dr_blob = blob.get("draft_room_state")
    if isinstance(dr_blob, dict):
        print(f"  blob['draft_room_state'].room_format = {dr_blob.get('room_format')!r}")
        print(f"  blob['draft_room_state'].room_your_team = {dr_blob.get('room_your_team')!r}")
    else:
        print(f"  blob['draft_room_state'] = {dr_blob!r}")
    ws = blob.get("baseball_workspace_state")
    if isinstance(ws, dict):
        print(f"  blob workspace.draft_state = {ws.get('draft_state')!r}")

    # ---------------------------------------------------------------
    # 4. REFRESH: brand-new session, apply the saved blob.
    # ---------------------------------------------------------------
    st2 = MagicMock()
    ss2: dict = {
        "active_page": "Draft Room Simulator",
        "main_sidebar_page": "Draft Room Simulator",
    }
    st2.session_state = ss2
    apply_baseball_disk_state(st2, blob)
    _snapshot("4. After refresh restore (apply_baseball_disk_state)", ss2)

    # ---------------------------------------------------------------
    # 5. prepare_global_fantasy_settings (called in prepare_baseball_workspace)
    # ---------------------------------------------------------------
    prepare_global_fantasy_settings(ss2)
    _snapshot("5. After prepare_global_fantasy_settings (post-restore)", ss2)

    # ---------------------------------------------------------------
    # RESULTS
    # ---------------------------------------------------------------
    print("\n" + "=" * 60)
    fmt_ok = ss2.get(GLOBAL_FORMAT_KEY) == "Points League"
    team_ok = ss2.get(GLOBAL_TEAM_KEY) == "Team 2"
    fmt_alias_ok = all(v == "Points League" for v in _fmt_aliases(ss2).values())
    team_alias_ok = all(v == "Team 2" for v in _team_aliases(ss2).values())
    print(f"FORMAT canonical survived refresh: {fmt_ok} (got {ss2.get(GLOBAL_FORMAT_KEY)!r})")
    print(f"FORMAT aliases all correct:        {fmt_alias_ok}")
    print(f"TEAM   canonical survived refresh: {team_ok} (got {ss2.get(GLOBAL_TEAM_KEY)!r})")
    print(f"TEAM   aliases all correct:        {team_alias_ok}")


if __name__ == "__main__":
    main()
