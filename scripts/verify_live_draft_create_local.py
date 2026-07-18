"""Production-path Solo + Shared create verification (no Streamlit Cloud).

Exercises begin → room init → start/create → lifecycle after End/Delete flags,
matching the streamlit_app create contract without opening a browser.
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
    for i in range(40):
        rows.append(
            {
                "playerID": f"p{i}",
                "fullName": f"Player {i}",
                "Primary Position": ["C", "1B", "2B", "3B", "SS", "OF", "OF", "DH"][i % 8],
                "proj_HR": 20,
                "proj_RBI": 70,
                "proj_R": 70,
                "proj_SB": 10,
                "proj_AVG": 0.270,
            }
        )
    return pd.DataFrame(rows)


def _base_session(**extra):
    session = {
        "auth_user_id": "daniel-local",
        "workspace_id": "local_verify",
        "_suite_active_workspace_id": "local_verify",
        "draft_room_participant_id": "daniel-local",
        "live_draft_setup_mode": "shared_multiplayer",
        "preferred_next_draft_mode": "shared_multiplayer",
        "live_draft_team_count": 2,
        "live_draft_picks_per_team": 4,
        "_live_draft_deleting": "done",
        "_live_draft_force_setup_after_delete": True,
    }
    session.update(extra)
    return session


def _build_room(pool: pd.DataFrame) -> dict:
    """Minimal room matching live_draft_init_room shape (avoids importing streamlit_app)."""
    teams = ["Team A", "Team B"]
    picks = []
    order = []
    pick_n = 1
    for rnd in range(1, 5):
        seq = teams if rnd % 2 == 1 else list(reversed(teams))
        for team in seq:
            order.append({"Pick": pick_n, "Round": rnd, "Team": team})
            pick_n += 1
    return {
        "draft_room_id": "LOCALVER1",
        "status": "not_started",
        "current_pick_index": 0,
        "config": {
            "league_name": "Verify League",
            "num_teams": 2,
            "picks_per_team": 4,
            "timer_seconds": 60,
            "teams": teams,
            "user_team": "Team A",
            "your_team": "Team A",
            "draft_setup_mode": "shared_multiplayer",
            "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "P": 0, "BN": 5},
        },
        "teams": teams,
        "pick_order": order,
        "draft_board": picks,
        "rosters": {t: [] for t in teams},
        "drafted_player_ids": [],
        "pool": pool,
    }


def verify_solo() -> dict:
    from live_draft_completion import LIFECYCLE_ACTIVE_DRAFT, resolve_live_draft_lifecycle
    from live_draft_creation_trace import (
        finalize_creation_receipt,
        init_creation_trace,
        note_creation_step,
        protect_new_room,
    )
    from live_draft_start_progress import begin_live_draft_start, finish_live_draft_start
    from live_draft_termination import reset_context_for_new_live_draft
    from live_draft_timer_logic import live_draft_reset_timer
    from draft_room_context import prepare_global_draft_context

    session = _base_session(
        live_draft_setup_mode="solo",
        preferred_next_draft_mode="solo",
    )
    # Simulate page bootstrap that previously wiped rooms under deleting=done.
    prepare_global_draft_context(session)
    init_creation_trace(session, mode="new")
    begin_live_draft_start(session, mode="new")
    note_creation_step(session, "begin_live_draft_start", ok=True)
    reset_context_for_new_live_draft(session)
    note_creation_step(session, "pool_build_start", ok=True)
    pool = _tiny_pool()
    note_creation_step(session, "pool_build_end", ok=True, pool_live_count=len(pool))
    room = _build_room(pool)
    room["config"]["draft_setup_mode"] = "solo"
    room["status"] = "in_progress"
    live_draft_reset_timer(room)
    session["live_draft_room"] = room
    note_creation_step(
        session,
        "solo_started",
        ok=True,
        draft_id=room["draft_room_id"],
        room_id=room["draft_room_id"],
    )
    protect_new_room(session)
    # Re-run prepare as the next page paint would — must not wipe.
    prepare_global_draft_context(session)
    life = resolve_live_draft_lifecycle(session, room=session.get("live_draft_room"))
    note_creation_step(session, "lifecycle_resolved", ok=True, lifecycle=life)
    finalize_creation_receipt(session, success=True, lifecycle=life)
    finish_live_draft_start(session, ok=True)
    assert isinstance(session.get("live_draft_room"), dict), "room wiped after create"
    assert life == LIFECYCLE_ACTIVE_DRAFT, life
    return {
        "ok": True,
        "mode": "solo",
        "lifecycle": life,
        "draft_id": room.get("draft_room_id"),
        "receipt": session.get("_live_draft_creation_receipt"),
    }


def verify_shared() -> dict:
    from draft_room_context import prepare_global_draft_context
    from draft_room_shared_state import LocalFileSharedRoomStore
    from live_draft_completion import LIFECYCLE_WAITING_SHARED_LOBBY, resolve_live_draft_lifecycle
    from live_draft_creation_trace import (
        finalize_creation_receipt,
        init_creation_trace,
        note_creation_step,
        protect_new_room,
    )
    from live_draft_setup_mode import SETUP_MODE_SHARED, finalize_shared_room_create
    from live_draft_start_progress import begin_live_draft_start, finish_live_draft_start
    from live_draft_termination import reset_context_for_new_live_draft
    from shared_room_membership_gate import assert_or_repair_before_shared_render

    tmp = tempfile.TemporaryDirectory()
    store = LocalFileSharedRoomStore(root=Path(tmp.name))
    session = _base_session()
    with mock.patch("draft_room_shared_state.get_shared_room_store", return_value=store):
        with mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False):
            prepare_global_draft_context(session)
            init_creation_trace(session, mode="prepare_shared")
            begin_live_draft_start(session, mode="prepare_shared")
            reset_context_for_new_live_draft(session)
            note_creation_step(session, "pool_build_end", ok=True)
            room = _build_room(_tiny_pool())
            note_creation_step(session, "shared_room_create_start", ok=True)
            code, err = finalize_shared_room_create(
                session, room, host_team="Team A", store=store
            )
            assert not err, err
            assert code, "missing room code"
            note_creation_step(
                session,
                "commissioner_registered",
                ok=True,
                draft_id=room["draft_room_id"],
                room_code=code,
            )
            protect_new_room(session)
            prepare_global_draft_context(session)
            may, gate_reason = assert_or_repair_before_shared_render(session)
            assert may, gate_reason
            life = resolve_live_draft_lifecycle(session, room=session.get("live_draft_room"))
            note_creation_step(session, "lifecycle_resolved", ok=True, lifecycle=life)
            finalize_creation_receipt(session, success=True, lifecycle=life)
            finish_live_draft_start(session, ok=True)
            assert life == LIFECYCLE_WAITING_SHARED_LOBBY, life
            assert session.get("active_shared_draft_room_code") == code
            assert str(session.get("preferred_next_draft_mode")) == SETUP_MODE_SHARED
            assert isinstance(session.get("live_draft_room"), dict), "shared room wiped"
    tmp.cleanup()
    return {
        "ok": True,
        "mode": "shared",
        "lifecycle": life,
        "draft_id": room.get("draft_room_id"),
        "room_code": code,
        "gate_reason": gate_reason,
        "receipt": session.get("_live_draft_creation_receipt"),
    }


def main() -> int:
    print("verify_live_draft_create_local: start")
    try:
        solo = verify_solo()
        print("SOLO_OK", {k: solo[k] for k in ("ok", "lifecycle", "draft_id")})
        print("SOLO_RECEIPT_STEP", (solo.get("receipt") or {}).get("completed_step"))
        shared = verify_shared()
        print(
            "SHARED_OK",
            {k: shared[k] for k in ("ok", "lifecycle", "draft_id", "room_code", "gate_reason")},
        )
        print("SHARED_RECEIPT_STEP", (shared.get("receipt") or {}).get("completed_step"))
    except Exception as exc:
        print("VERIFY_FAILED", type(exc).__name__, exc)
        traceback.print_exc()
        return 1
    print("ALL_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
