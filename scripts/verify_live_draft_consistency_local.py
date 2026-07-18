"""Local production-path: create → park → continue → replace."""

from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _room() -> dict:
    return {
        "draft_room_id": "CONS01",
        "status": "in_progress",
        "current_pick_index": 1,
        "config": {
            "num_teams": 2,
            "your_team": "Team A",
            "user_team": "Team A",
            "teams": ["Team A", "Team B"],
            "draft_setup_mode": "shared_multiplayer",
            "timer_seconds": 30,
            "picks_per_team": 4,
        },
        "teams": ["Team A", "Team B"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team A"},
            {"Pick": 2, "Round": 1, "Team": "Team B"},
            {"Pick": 3, "Round": 2, "Team": "Team B"},
            {"Pick": 4, "Round": 2, "Team": "Team A"},
        ],
        "draft_board": [{"Pick": 1, "Team": "Team A", "Player": "P0", "playerID": "p0"}],
        "rosters": {"Team A": [], "Team B": []},
        "drafted_player_ids": ["p0"],
        "pool": pd.DataFrame(
            [{"playerID": f"p{i}", "fullName": f"P{i}", "Primary Position": "OF"} for i in range(12)]
        ),
    }


def main() -> int:
    from draft_room_context import create_and_host_shared_room, join_shared_draft_room
    from draft_room_shared_state import LocalFileSharedRoomStore, bump_revision
    from live_draft_completion import LIFECYCLE_WAITING_SHARED_LOBBY, resolve_live_draft_lifecycle
    from live_draft_resumable_slot import (
        RESUMABLE_LIVE_DRAFT_SLOT_KEY,
        continue_saved_draft,
        replace_resumable_and_arm_start,
    )
    from live_draft_resume_lobby import stamp_resume_reserved_on_document
    from live_draft_setup_mode import SETUP_MODE_SHARED, set_live_draft_setup_mode
    from shared_draft_permissions import is_canonical_commissioner
    from shared_live_draft_snapshot import build_shared_live_draft_snapshot
    from shared_room_membership_gate import assert_or_repair_before_shared_render

    print("verify_live_draft_consistency_local: start")
    tmp = tempfile.TemporaryDirectory()
    store = LocalFileSharedRoomStore(root=Path(tmp.name))
    try:
        with mock.patch("draft_room_shared_state.get_shared_room_store", return_value=store):
            with mock.patch("draft_room_context.get_shared_room_store", return_value=store):
                with mock.patch(
                    "draft_room_membership.shared_room_requires_auth", return_value=False
                ):
                    daniel = {
                        "auth_user_id": "daniel",
                        "draft_room_participant_id": "daniel",
                        "live_draft_setup_mode": SETUP_MODE_SHARED,
                        "preferred_next_draft_mode": SETUP_MODE_SHARED,
                    }
                    set_live_draft_setup_mode(daniel, SETUP_MODE_SHARED)
                    room = _room()
                    code, doc = create_and_host_shared_room(
                        daniel, room, host_team="Team A", store=store
                    )
                    assert code and isinstance(doc, dict), "create failed"
                    coakley = {
                        "auth_user_id": "coakley11",
                        "draft_room_participant_id": "coakley11",
                    }
                    ok, msg, _ = join_shared_draft_room(
                        coakley, code, requested_team="Team B", store=store
                    )
                    assert ok, msg
                    print("JOIN_OK", code)

                    # Snapshot agreement on pick/team.
                    d_snap = build_shared_live_draft_snapshot(daniel, room=daniel.get("live_draft_room"), document=store.load(code))
                    c_snap = build_shared_live_draft_snapshot(coakley, room=coakley.get("live_draft_room"), document=store.load(code))
                    assert d_snap.get("on_clock_team") == c_snap.get("on_clock_team"), (
                        d_snap.get("on_clock_team"),
                        c_snap.get("on_clock_team"),
                    )
                    assert d_snap.get("current_pick") == c_snap.get("current_pick")
                    print("SNAP_OK", d_snap.get("on_clock_team"), d_snap.get("current_pick"), "rev", d_snap.get("revision"))

                    # Park + continue.
                    parked = stamp_resume_reserved_on_document(store.load(code))
                    store.save(bump_revision(parked))
                    daniel[RESUMABLE_LIVE_DRAFT_SLOT_KEY] = {
                        "kind": "resumable_live_draft_slot",
                        "draft_id": "CONS01",
                        "room_id": "CONS01",
                        "room_code": code,
                        "is_shared": True,
                        "participant_id": "daniel",
                        "participant_team": "Team A",
                        "room": dict(daniel.get("live_draft_room") or room),
                        "queues": {"draft_queue": ["KeepMe"]},
                        "summary": {"current_pick": 2, "total_picks": 4, "num_teams": 2},
                    }
                    daniel.pop("live_draft_room", None)
                    daniel.pop("active_shared_draft_room_code", None)
                    cont = continue_saved_draft(daniel)
                    assert cont.get("ok"), cont
                    may, reason = assert_or_repair_before_shared_render(daniel)
                    assert may, reason
                    life = resolve_live_draft_lifecycle(daniel, room=daniel.get("live_draft_room"))
                    assert life == LIFECYCLE_WAITING_SHARED_LOBBY, life
                    assert int((daniel.get("live_draft_room") or {}).get("current_pick_index") or 0) == 1
                    assert is_canonical_commissioner(daniel, store.load(code))
                    print("CONTINUE_OK", life)

                    # Replace (create-first transaction).
                    rep = replace_resumable_and_arm_start(daniel)
                    assert rep.get("ok"), rep
                    new_code = str(rep.get("new_room_code") or "")
                    assert new_code and new_code != code, rep
                    assert daniel.get("active_shared_draft_room_code") == new_code
                    assert str((store.load(code) or {}).get("status") or "").lower() == "deleted"
                    print("REPLACE_OK", new_code, "tombstoned", code)
    except Exception as exc:
        print("VERIFY_FAILED", type(exc).__name__, exc)
        traceback.print_exc()
        tmp.cleanup()
        return 1
    tmp.cleanup()
    print("ALL_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
