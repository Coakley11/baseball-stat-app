"""Faithful offline repro of the draft-settings / format revert through the REAL
build_baseball_disk_state -> apply_baseball_disk_state cycle (not a synthetic one).

If the value reverts here, we've located the drop point in the durable cycle.
If it survives here, the failure is environment-specific (Streamlit widget lifecycle
/ cloud timing) and the in-app trace is required to confirm.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state
from global_fantasy_settings_state import on_alias_format_changed, on_alias_team_changed


def case(title: str, page: str, edits: dict, canonical_format: str | None = None, canonical_team: str | None = None):
    print("\n" + "=" * 76)
    print(title)
    print("=" * 76)

    # 1) User is on `page`, edits settings. Simulate widget keys + canonical writes.
    st = MagicMock()
    ss = {
        "active_page": page,
        "main_sidebar_page": page,
        "_page_state_last_active": page,
        "_suite_last_persisted_page": page,
        "page_filter_state": {},
    }
    ss.update(edits)
    st.session_state = ss
    if canonical_format is not None:
        on_alias_format_changed(ss, _format_alias_for_page(page))
    if canonical_team is not None:
        on_alias_team_changed(ss, _team_alias_for_page(page))

    print("-- after edit (live session) --")
    for k in edits:
        print(f"   {k:34} = {ss.get(k)!r}")
    print(f"   {'room_format (canonical)':34} = {ss.get('room_format')!r}")
    print(f"   {'room_your_team (canonical)':34} = {ss.get('room_your_team')!r}")

    # 2) Build the durable blob (this is what is saved to cloud/disk).
    blob = build_baseball_disk_state(st)
    pf_block = (blob.get("page_filter_state") or {}).get(page) or {}
    print("-- saved blob --")
    for k in edits:
        print(f"   blob.page_filter_state[{k}] = {pf_block.get(k)!r}")
    print(f"   blob.room_format             = {blob.get('room_format')!r}")
    print(f"   blob.room_your_team          = {blob.get('room_your_team')!r}")

    # 3) Browser refresh: brand-new session, apply the durable blob.
    st2 = MagicMock()
    st2.session_state = {}
    apply_baseball_disk_state(st2, blob)
    ss2 = st2.session_state

    print("-- after refresh (restored session) --")
    reverted = []
    for k, v in edits.items():
        got = ss2.get(k)
        ok = got == v
        print(f"   {k:34} = {got!r}   {'OK' if ok else 'REVERTED (expected ' + repr(v) + ')'}")
        if not ok:
            reverted.append(k)
    print(f"   room_format (canonical)            = {ss2.get('room_format')!r}")
    print(f"   room_your_team (canonical)         = {ss2.get('room_your_team')!r}")
    if reverted:
        print(f"!! REVERTED KEYS: {reverted}")
    else:
        print("OK: all tracked settings survived the durable cycle.")


def _format_alias_for_page(page: str) -> str:
    return {
        "Draft Assistant Simulator": "draft_format",
        "Draft Room Simulator": "room_format",
        "Draft Simulation Test Mode": "draft_lab_scoring_type",
    }.get(page, "draft_format")


def _team_alias_for_page(page: str) -> str:
    return {
        "Draft Assistant Simulator": "draft_assistant_synced_team",
        "Draft Room Simulator": "room_your_team",
    }.get(page, "draft_assistant_synced_team")


def main() -> None:
    case(
        "Draft Assistant Simulator — change window + format",
        "Draft Assistant Simulator",
        {"draft_window": 4, "draft_format": "Points League", "draft_top_n": 50},
        canonical_format="Points League",
    )
    case(
        "Draft Room Simulator — change format + team + rounds",
        "Draft Room Simulator",
        {"room_format": "Points League", "room_your_team": "Daniel", "room_rounds": 25, "room_window": 5},
        canonical_format="Points League",
        canonical_team="Daniel",
    )
    case(
        "Draft Simulation Test Mode — change window + scoring",
        "Draft Simulation Test Mode",
        {"draft_lab_window": 5, "draft_lab_scoring_type": "Points League", "draft_lab_picks_per_team": 20},
        canonical_format="Points League",
    )
    case(
        "Live Draft Room — change league name + scoring",
        "Live Draft Room",
        {"live_draft_league_name": "My League", "live_draft_scoring": "Points League", "live_draft_team_count": 12},
    )


if __name__ == "__main__":
    main()
