"""Production-path Shared guest join: Daniel creates → Coakley11 joins Team B.

Exercises create_and_host_shared_room + join_shared_draft_room with the real
module-level get_shared_room_store resolution (no injected store on join).
"""

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


def _tiny_pool() -> pd.DataFrame:
    rows = []
    for i in range(20):
        rows.append(
            {
                "playerID": f"p{i}",
                "fullName": f"Player {i}",
                "Primary Position": ["C", "1B", "2B", "3B", "SS", "OF", "OF", "DH"][i % 8],
            }
        )
    return pd.DataFrame(rows)


def _two_team_room() -> dict:
    teams = ["Team A", "Team B"]
    return {
        "draft_room_id": "GJOIN01",
        "status": "not_started",
        "current_pick_index": 0,
        "config": {
            "league_name": "Guest Join Verify",
            "num_teams": 2,
            "picks_per_team": 4,
            "teams": teams,
            "user_team": "Team A",
            "your_team": "Team A",
            "draft_setup_mode": "shared_multiplayer",
        },
        "teams": teams,
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team A"},
            {"Pick": 2, "Round": 1, "Team": "Team B"},
        ],
        "draft_board": [],
        "rosters": {t: [] for t in teams},
        "drafted_player_ids": [],
        "pool": _tiny_pool(),
    }


def main() -> int:
    from draft_room_context import create_and_host_shared_room, join_shared_draft_room
    from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, LocalFileSharedRoomStore
    from live_draft_setup_mode import SETUP_MODE_SHARED, set_live_draft_setup_mode
    from shared_draft_permissions import is_canonical_commissioner

    print("verify_guest_join_local: start")
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
                        "workspace_id": "daniel_ws",
                        "_suite_active_workspace_id": "daniel_ws",
                        "live_draft_setup_mode": SETUP_MODE_SHARED,
                        "preferred_next_draft_mode": SETUP_MODE_SHARED,
                    }
                    set_live_draft_setup_mode(daniel, SETUP_MODE_SHARED)
                    code, document = create_and_host_shared_room(
                        daniel, _two_team_room(), host_team="Team A", store=store
                    )
                    assert code and isinstance(document, dict), "create failed"
                    host_doc = store.load(code)
                    assert is_canonical_commissioner(daniel, host_doc), "Daniel should be commissioner"
                    print("DANIEL_CREATE_OK", code)

                    # Invalid code must not crash.
                    bad_ok, bad_msg, _ = join_shared_draft_room(
                        {"draft_room_participant_id": "coakley11"},
                        "ZZZZZZ",
                        requested_team="Team B",
                    )
                    assert not bad_ok and "not found" in bad_msg.lower(), bad_msg
                    print("INVALID_CODE_OK", bad_msg)

                    coakley = {
                        "auth_user_id": "coakley11",
                        "draft_room_participant_id": "coakley11",
                        "workspace_id": "coakley_ws",
                        "_suite_active_workspace_id": "coakley_ws",
                        "live_draft_setup_mode": SETUP_MODE_SHARED,
                    }
                    # Critical path: no store= injection (module get_shared_room_store).
                    ok, msg, doc = join_shared_draft_room(
                        coakley, code, requested_team="Team B"
                    )
                    assert ok, msg
                    assert coakley.get(ACTIVE_SHARED_ROOM_CODE_KEY) == code
                    team = str(
                        coakley.get("draft_room_participant_team")
                        or ((doc or {}).get("participants") or {})
                        .get("coakley11", {})
                        .get("assigned_team")
                        or ""
                    )
                    assert team == "Team B", team
                    assert not is_canonical_commissioner(coakley, doc), "guest must not be commissioner"
                    assert str((doc or {}).get("commissioner_participant_id") or "") == "daniel"
                    print("COAKLEY_JOIN_OK", {"team": team, "commissioner": False, "msg": msg})
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
