"""Time the Solo create critical path locally (no Streamlit UI / Cloud).

Measures: setup → pool (tiny fixture) → room init → session install → deferred persist.
Also probes whether force_save of a full pool would dominate create time.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _tiny_pool(n: int = 200) -> pd.DataFrame:
    rows = []
    for i in range(n):
        rows.append(
            {
                "playerID": f"p{i}",
                "fullName": f"Player {i}",
                "Primary Position": ["C", "1B", "2B", "3B", "SS", "OF", "OF", "DH"][i % 8],
                "Expected Fantasy Value": 100 - (i % 80),
                "proj_HR": 20,
                "proj_RBI": 70,
                "proj_R": 70,
                "proj_SB": 10,
                "proj_AVG": 0.270,
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    from live_draft_completion import LIFECYCLE_ACTIVE_DRAFT, resolve_live_draft_lifecycle
    from live_draft_creation_trace import finalize_creation_receipt, init_creation_trace
    from live_draft_solo_create import (
        flush_deferred_create_persist,
        mark_deferred_create_persist,
        note_timed_step,
    )
    from live_draft_start_progress import begin_live_draft_start, finish_live_draft_start
    from live_draft_timer_logic import live_draft_reset_timer

    timings: dict[str, float] = {}
    t_all = time.perf_counter()

    session: dict = {
        "auth_user_id": "daniel-local",
        "workspace_id": "local_time",
        "live_draft_setup_mode": "solo",
        "preferred_next_draft_mode": "solo",
        "draft_queue": [],
    }
    init_creation_trace(session, mode="new")
    begin_live_draft_start(session, mode="new")

    t0 = time.perf_counter()
    note_timed_step(session, "settings_captured", ok=True, t_step0=t0)
    timings["setup_validated_ms"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    note_timed_step(session, "pool_build_start", ok=True, t_step0=t0)
    pool = _tiny_pool(200)
    note_timed_step(
        session,
        "pool_build_end",
        ok=True,
        t_step0=t0,
        pool_live_count=len(pool),
        pool_warm=True,
    )
    timings["player_pool_loaded_ms"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    teams = ["Team A", "Team B"]
    pick_order = []
    n = 1
    for rnd in range(1, 5):
        seq = teams if rnd % 2 else list(reversed(teams))
        for team in seq:
            pick_order.append({"Pick": n, "Round": rnd, "Team": team})
            n += 1
    room = {
        "draft_room_id": "TIMELOCAL",
        "status": "in_progress",
        "current_pick_index": 0,
        "teams": teams,
        "pick_order": pick_order,
        "draft_board": [],
        "drafted_player_ids": [],
        "rosters": {t: [] for t in teams},
        "pool": pool.copy(),
        "config": {
            "num_teams": 2,
            "picks_per_team": 4,
            "timer_seconds": 30,
            "teams": teams,
            "your_team": "Team A",
            "user_team": "Team A",
            "draft_setup_mode": "solo",
        },
    }
    live_draft_reset_timer(room)
    note_timed_step(
        session,
        "room_initialized",
        ok=True,
        t_step0=t0,
        draft_id=room["draft_room_id"],
        pick_order_len=len(pick_order),
    )
    timings["pick_order_created_ms"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    session["live_draft_room"] = room
    mark_deferred_create_persist(session)
    note_timed_step(
        session,
        "session_installed",
        ok=True,
        t_step0=t0,
        draft_id=room["draft_room_id"],
    )
    timings["draft_state_installed_ms"] = (time.perf_counter() - t0) * 1000

    life = resolve_live_draft_lifecycle(session, room=room)
    finalize_creation_receipt(session, success=True, lifecycle=life)
    finish_live_draft_start(session, ok=True)
    assert life == LIFECYCLE_ACTIVE_DRAFT, life

    t0 = time.perf_counter()
    flush_deferred_create_persist(None, session, persist_room_fn=None)
    timings["persistence_completed_ms"] = (time.perf_counter() - t0) * 1000
    timings["create_to_open_ms"] = (time.perf_counter() - t_all) * 1000

    # Probe: how expensive would a naive pool.copy + force path feel on a larger frame?
    t0 = time.perf_counter()
    big = _tiny_pool(2500)
    _ = big.copy()
    timings["pool_2500_copy_ms"] = (time.perf_counter() - t0) * 1000

    receipt = session.get("_live_draft_creation_receipt") or {}
    print("ok=True")
    print(f"lifecycle={life}")
    print(f"draft_id={room['draft_room_id']}")
    print(f"attempt_id={receipt.get('attempt_id')}")
    print(f"completed_step={receipt.get('completed_step')}")
    for k, v in timings.items():
        print(f"{k}={v:.1f}")
    print(f"receipt_keys={[k for k in receipt if str(k).endswith('_ms')]}")
    # Budget: local fixture path should be well under 5s create-to-open.
    if timings["create_to_open_ms"] > 5000:
        print("FAIL: create_to_open_ms exceeds 5000")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
