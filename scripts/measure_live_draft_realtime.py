"""Measure Live Draft transactional latencies (engine path — no Streamlit Cloud network).

Reports actual milliseconds for queue add/remove, manual-style pick commit, timer
auto-pick selection+persist against a local shared-room store, and guest sync apply.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd


def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000.0


def _pool(n: int = 40) -> pd.DataFrame:
    rows = []
    for i in range(n):
        rows.append(
            {
                "playerID": f"p{i}",
                "fullName": f"Player {i}",
                "Primary Position": "OF" if i % 2 == 0 else "SS",
                "Team": "NYY",
            }
        )
    return pd.DataFrame(rows)


def _room(**overrides):
    teams = ["Team A", "Team B"]
    pool = _pool()
    base = {
        "draft_room_id": "LAT01",
        "status": "in_progress",
        "current_pick_index": 0,
        "config": {
            "num_teams": 2,
            "your_team": "Team A",
            "timer_seconds": 10,
            "auto_pick_rule": "balanced recommendation",
            "queue_auto_pick": True,
            "allow_free_pool_drafting": True,
            "picks_per_team": 4,
        },
        "teams": teams,
        "pick_order": [
            {"Pick": i + 1, "Round": (i // 2) + 1, "Team": teams[i % 2]} for i in range(8)
        ],
        "draft_board": [],
        "rosters": {t: [] for t in teams},
        "drafted_player_ids": [],
        "pool": pool,
        "timer_deadline": time.time() + 10,
        "timer_handled_index": -1,
    }
    base.update(overrides)
    return base


def main() -> None:
    from draft_room_context import create_and_host_shared_room, join_shared_draft_room, sync_shared_draft_room
    from draft_room_shared_state import (
        ACTIVE_SHARED_ROOM_CODE_KEY,
        LocalFileSharedRoomStore,
        SHARED_ROOM_META_KEY,
        bump_revision,
        invalidate_shared_room_document_cache,
        reset_shared_room_store_for_tests,
        shared_document_room_blob,
    )
    from draft_state import add_player_to_draft_queue, remove_player_from_draft_queue
    from live_draft_expired_pick import run_expired_autopick_once
    from live_draft_pick_engine import live_draft_make_pick
    from live_draft_pick_commit import persist_applied_pick
    from live_draft_rerun_scope import live_draft_expensive_recompute_required, mark_live_draft_queue_tick
    from live_draft_state import LIVE_DRAFT_ROOM_KEY
    from live_draft_timer_logic import live_draft_reset_timer

    results: dict[str, float] = {}

    # --- Queue add / remove (local engine) ---
    session = {"draft_queue": []}
    with mock.patch("draft_state._sync_participant_workflow_if_multiplayer") as sync_mp:
        with mock.patch("live_draft_recommendations.live_draft_recommendations") as rec_engine:
            # Warm imports / first-call overhead so reported numbers reflect steady state.
            add_player_to_draft_queue(session, "Warmup Player")
            remove_player_from_draft_queue(session, "Warmup Player")
            t0 = time.perf_counter()
            add_player_to_draft_queue(session, "Player 1")
            results["queue_add_ms"] = _ms(t0)
            sync_mp.assert_not_called()
            rec_engine.assert_not_called()
            mark_live_draft_queue_tick(session)
            assert live_draft_expensive_recompute_required(session) is False

            t0 = time.perf_counter()
            remove_player_from_draft_queue(session, "Player 1")
            results["queue_remove_ms"] = _ms(t0)

    # --- Manual pick commit (local room + shared store) ---
    tmp = tempfile.TemporaryDirectory()
    store = LocalFileSharedRoomStore(root=Path(tmp.name))
    reset_shared_room_store_for_tests(store)
    host = {
        "auth_user_id": "user:daniel",
        "draft_room_participant_id": "user:daniel",
        "room_your_team": "Team A",
    }
    guest = {
        "auth_user_id": "user:coakley11",
        "draft_room_participant_id": "user:coakley11",
        "room_your_team": "Team B",
    }
    with mock.patch("draft_room_shared_state.get_shared_room_store", return_value=store):
        with mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False):
            room = _room()
            code, _ = create_and_host_shared_room(host, room, store=store)
            join_shared_draft_room(guest, code, requested_team="Team B", store=store)
            host[ACTIVE_SHARED_ROOM_CODE_KEY] = code
            host[LIVE_DRAFT_ROOM_KEY] = room
            live_draft_reset_timer(room)

            # Seed a cheap rec cache so autopick does not rebuild scoring.
            host["_live_draft_rec_cache"] = {
                "key": "skip",
                "top_rec": room["pool"].head(3),
            }

            # Manual pick path: make_pick + persist
            available = room["pool"].iloc[0].to_dict()
            t0 = time.perf_counter()
            ok, msg = live_draft_make_pick(room, available, pick_source="Manual")
            assert ok, msg
            with mock.patch("draft_room_context.is_multiplayer_draft_active", return_value=True):
                persisted = persist_applied_pick(
                    host,
                    room,
                    source="manual",
                    board_size_before=0,
                    idx_before=0,
                    fast_path=True,
                )
            results["manual_pick_ms"] = _ms(t0)
            assert persisted.ok, persisted.message

            # Timer auto-pick on expired room
            room2 = host[LIVE_DRAFT_ROOM_KEY]
            room2["timer_deadline"] = time.time() - 1
            room2["status"] = "in_progress"
            # Ensure pool still has players
            t0 = time.perf_counter()
            with mock.patch("live_draft_expired_pick._multiplayer_autopick_allowed", return_value=True):
                with mock.patch("draft_room_context.is_multiplayer_draft_active", return_value=True):
                    # Prefer queue-first / cache path
                    host["draft_queue"] = [str(room2["pool"].iloc[1]["fullName"])]
                    result = run_expired_autopick_once(host, room2, source="measure")
            results["timer_autopick_ms"] = _ms(t0)
            results["timer_autopick_ok"] = 1.0 if result.ok else 0.0

            # Guest synchronization: host advanced → guest discards stale revision
            remote = store.load(code)
            assert remote is not None
            blob = dict(shared_document_room_blob(remote) or {})
            advanced = bump_revision(
                remote,
                live_room={
                    **blob,
                    "current_pick_index": int(blob.get("current_pick_index") or 0) + 1,
                    "timer_deadline": time.time() + 9,
                    "status": "in_progress",
                    "draft_board": list(blob.get("draft_board") or [])
                    + [{"Pick": 99, "Team": "Team A", "playerID": "px", "fullName": "Sync"}],
                },
            )
            store.save(advanced)
            guest[ACTIVE_SHARED_ROOM_CODE_KEY] = code
            guest[SHARED_ROOM_META_KEY] = {
                "revision": int((remote.get("revision") or 1)),
                "room_code": code,
            }
            guest[LIVE_DRAFT_ROOM_KEY] = dict(blob)
            invalidate_shared_room_document_cache(guest, code)
            t0 = time.perf_counter()
            changed = sync_shared_draft_room(guest, force=True, store=store)
            results["guest_sync_ms"] = _ms(t0)
            results["guest_sync_changed"] = 1.0 if changed else 0.0

    reset_shared_room_store_for_tests(None)
    tmp.cleanup()

    print("=== Live Draft latency measurements (local engine / local shared store) ===")
    for key in (
        "queue_add_ms",
        "queue_remove_ms",
        "manual_pick_ms",
        "timer_autopick_ms",
        "guest_sync_ms",
    ):
        print(f"{key}: {results.get(key, -1):.1f}")
    print(f"timer_autopick_ok: {bool(results.get('timer_autopick_ok'))}")
    print(f"guest_sync_changed: {bool(results.get('guest_sync_changed'))}")
    print(
        "NOTE: These are engine+local-store times. Streamlit Cloud full-page paint and "
        "Supabase RTT add additional latency on deployed builds; Dev Mode action latency "
        "captions report those when interacting in the browser."
    )


if __name__ == "__main__":
    main()
