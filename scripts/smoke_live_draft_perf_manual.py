#!/usr/bin/env python3
"""Developer Mode smoke test — Live Draft perf slice (real player pool).

Simulates the UI hot path headlessly with dev perf timings enabled.

Run from repo root:
  python scripts/smoke_live_draft_perf_manual.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

MAX_QUEUE_MS = 50.0
MAX_DRAFT_MS = 1200.0
MAX_PREPARE_TOTAL_MS = 100.0


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    raise SystemExit(1)


def _ok(msg: str) -> None:
    print(f"PASS: {msg}")


def _load_real_pool(session: dict) -> pd.DataFrame:
    """Load Lahman-backed player pool (same data source as the app, no Streamlit import)."""
    sa = ROOT / "streamlit_app.py"

    def _snip(start: int, end: int) -> str:
        return "\n".join(sa.read_text(encoding="utf-8").splitlines()[start - 1 : end])

    g: dict = {"pd": pd, "np": __import__("numpy"), "Path": Path, "BASE_DIR": ROOT}

    def read_required_csv(filename: str) -> pd.DataFrame:
        p = ROOT / filename
        if not p.exists():
            raise FileNotFoundError(p)
        return pd.read_csv(p, low_memory=False)

    g["read_required_csv"] = read_required_csv
    exec(compile("\n\n".join([_snip(287, 382), _snip(1539, 1558), _snip(5874, 5982)]), str(sa), "exec"), g, g)
    _batting, yearly_df, _people = g["load_data"]()
    max_year = int(pd.to_numeric(yearly_df["yearID"], errors="coerce").max())
    window = int(session.get("room_window") or 3)
    recent = yearly_df[yearly_df["yearID"] >= max_year - window + 1].copy()
    agg = (
        recent.groupby(["playerID", "fullName"], as_index=False)[["G", "HR", "RBI", "SB", "R"]]
        .sum()
    )
    agg = agg[(agg["G"] >= 30)].copy()
    pos = (
        recent.sort_values(["playerID", "G"], ascending=[True, False])
        .drop_duplicates("playerID")[["playerID", "primaryPos"]]
    )
    pool = agg.merge(pos, on="playerID", how="left")
    pool["Primary Position"] = pool["primaryPos"].fillna("OF")
    pool["Expected Fantasy Value"] = (
        pool["HR"] * 4 + pool["RBI"] * 2 + pool["R"] + pool["SB"] * 2 + pool["G"] * 0.05
    )
    pool["Model Rank"] = pool["Expected Fantasy Value"].rank(ascending=False, method="min").astype(int)
    pool["Market Rank"] = pool["Model Rank"]
    if len(pool) < 50:
        _fail(f"real pool too small ({len(pool)} rows) — Lahman CSV files may be missing")
    return pool.copy()


def _build_room(pool: pd.DataFrame, team: str = "Daniel") -> dict:
    teams = ["Daniel", "Rival A", "Rival B", "Rival C"]
    return {
        "status": "in_progress",
        "current_pick_index": 0,
        "draft_room_id": "smoke-real-pool",
        "config": {
            "num_teams": 4,
            "picks_per_team": 15,
            "fantasy_format": "5x5 Roto",
            "scoring_type": "Roto (5x5)",
            "your_team": team,
            "slot_c": 1,
            "slot_1b": 1,
            "slot_2b": 1,
            "slot_3b": 1,
            "slot_ss": 1,
            "slot_of": 3,
            "slot_dh": 1,
            "slot_p": 5,
            "slot_bench": 3,
        },
        "teams": teams,
        "pick_order": [
            {"Pick": j + 1, "Round": (j // 4) + 1, "Team": t}
            for j, t in enumerate(teams * 15)
        ],
        "draft_board": [],
        "rosters": {t: [] for t in teams},
        "drafted_player_ids": [],
        "pool": pool,
    }


def _action_ms(session: dict, phase: str) -> list[float]:
    rows = session.get("_live_draft_perf_actions") or []
    return [float(r.get("elapsed_ms") or 0) for r in rows if r.get("phase") == phase]


def main() -> int:
    from draft_state import add_player_to_draft_queue, remove_player_from_draft_queue
    from live_draft_perf import recent_live_draft_actions
    from live_draft_pick_commit import commit_manual_live_pick
    from live_draft_state import (
        LIVE_DRAFT_BOARD_SYNC_PENDING_KEY,
        LIVE_DRAFT_DEFERRED_PICK_ACTIVITY_KEY,
        LIVE_DRAFT_ROOM_KEY,
        LIVE_DRAFT_STATE_KEY,
        flush_deferred_live_draft_pick_effects,
        live_draft_get_available,
        prepare_live_draft_state,
        room_to_persist_dict,
    )
    from live_draft_ui_cache import cached_live_draft_get_available

    session: dict = {
        "_page_perf_ns": {"page": "Live Draft Room", "timings": {}, "started_at": time.perf_counter()},
        "draft_queue": [],
        "room_your_team": "Daniel",
        "room_format": "5x5 Roto",
        "room_window": 3,
        "fantasy_draft_projection_style": "Balanced",
        "draft_use_ml_blend": True,
        "draft_ml_blend_weight": 0.12,
        "_lahman_max_year": 2024,
    }

    print("Loading real player pool (may take 30-90s)...")
    t0 = time.perf_counter()
    pool = _load_real_pool(session)
    print(f"  pool rows: {len(pool)} ({time.perf_counter() - t0:.1f}s)")

    room = _build_room(pool)
    session[LIVE_DRAFT_ROOM_KEY] = room
    session[LIVE_DRAFT_STATE_KEY] = room_to_persist_dict(room)

    patches = [
        patch("page_perf_phases.dev_perf_enabled", return_value=True),
        patch("draft_room_state.resolve_active_draft_source", return_value="live"),
        patch("baseball_persistent_state.force_save_baseball_state", return_value=True),
    ]
    for p in patches:
        p.start()

    try:
        prepare_live_draft_state(session)

        pick_name = str(pool.iloc[0].get("fullName") or pool.iloc[0].get("Player") or "").strip()
        second_name = str(pool.iloc[1].get("fullName") or pool.iloc[1].get("Player") or "").strip()
        if not pick_name:
            _fail("could not resolve draft player name from pool")

        add_player_to_draft_queue(session, pick_name)
        add_player_to_draft_queue(session, second_name)
        remove_player_from_draft_queue(session, second_name)

        queue_add_ms = _action_ms(session, "live_draft_queue_add")
        queue_remove_ms = _action_ms(session, "live_draft_queue_remove")
        if not queue_add_ms or max(queue_add_ms) > MAX_QUEUE_MS:
            _fail(f"queue add too slow: {queue_add_ms} (max {MAX_QUEUE_MS}ms)")
        _ok(f"queue add instant ({max(queue_add_ms):.1f}ms max)")
        if queue_remove_ms and max(queue_remove_ms) > MAX_QUEUE_MS:
            _fail(f"queue remove too slow: {queue_remove_ms}")
        _ok(f"queue remove instant ({max(queue_remove_ms) if queue_remove_ms else 0:.1f}ms)")

        avail_before = len(cached_live_draft_get_available(session, room))
        player_row = pool.iloc[0].to_dict()

        t_draft = time.perf_counter()
        commit = commit_manual_live_pick(session, room, player_row, source="smoke_manual")
        draft_ms = (time.perf_counter() - t_draft) * 1000.0
        perf_draft_ms = _action_ms(session, "live_draft_pick_commit")
        if perf_draft_ms:
            draft_ms = max(draft_ms, max(perf_draft_ms))

        if not commit.ok:
            _fail(f"draft pick failed: {commit.message}")
        if draft_ms > MAX_DRAFT_MS:
            _fail(f"draft pick too slow: {draft_ms:.0f}ms (max {MAX_DRAFT_MS}ms)")
        _ok(f"draft player faster ({draft_ms:.0f}ms)")

        room = session.get(LIVE_DRAFT_ROOM_KEY) or room
        if int(room.get("current_pick_index") or 0) < 1:
            _fail("pick index did not advance")
        board_len = len(room.get("draft_board") or [])
        if board_len != 1:
            _fail(f"draft board size wrong: {board_len}")
        roster = list((room.get("rosters") or {}).get("Daniel") or [])
        if not roster:
            _fail("Daniel roster empty after pick")
        roster_name = str(roster[0].get("fullName") or roster[0].get("Player") or "")
        if roster_name.lower() != pick_name.lower():
            _fail(f"roster player mismatch: {roster_name!r} vs {pick_name!r}")
        _ok("draft state intact (board, index, roster)")

        avail_after = len(live_draft_get_available(room))
        if avail_after >= avail_before:
            _fail(f"available pool did not shrink: {avail_before} -> {avail_after}")
        _ok(f"drafted player removed from pool ({avail_before} -> {avail_after})")

        if not session.get(LIVE_DRAFT_BOARD_SYNC_PENDING_KEY):
            _fail("deferred board sync flag missing after pick")
        _ok("deferred canonical board sync scheduled")

        if not session.get(LIVE_DRAFT_DEFERRED_PICK_ACTIVITY_KEY):
            _fail("deferred activity flag missing after pick")
        _ok("deferred activity logging scheduled")

        from draft_room_state import get_canonical_draft_board, table_pick_count

        board_before_flush = table_pick_count(session.get("draft_room_table"))
        flush_deferred_live_draft_pick_effects(session)
        if session.get(LIVE_DRAFT_BOARD_SYNC_PENDING_KEY) or session.get(LIVE_DRAFT_DEFERRED_PICK_ACTIVITY_KEY):
            _fail("deferred flags not cleared after flush")
        _ok("deferred flush completed")

        board_after = get_canonical_draft_board(session)
        picks = table_pick_count(board_after)
        if picks < 1:
            _fail(f"canonical board empty after flush (picks={picks}, before={board_before_flush})")
        if "Player" in board_after.columns:
            filled = board_after[board_after["Player"].astype(str).str.strip().ne("")]
            if filled.empty:
                _fail("canonical board has no filled player rows after flush")
            top_name = str(filled.iloc[0]["Player"]).strip()
            if top_name.lower() != pick_name.lower():
                _fail(f"canonical board player mismatch: {top_name!r}")
        _ok("canonical draft board updated after flush")

        prepare_live_draft_state(session)
        prepare_live_draft_state(session)
        prep_total_ms = float(session.get("_page_perf_ns", {}).get("timings", {}).get("live_draft_prepare_state") or 0) * 1000
        if prep_total_ms > MAX_PREPARE_TOTAL_MS:
            _fail(f"prepare_state too slow on re-entry: {prep_total_ms:.0f}ms")
        _ok(f"prepare short-circuit on section revisit ({prep_total_ms:.0f}ms total)")

        actions = recent_live_draft_actions(session, limit=8)
        print("\nRecent dev actions:")
        for row in reversed(actions):
            cache = f" cache={row['cache']}" if row.get("cache") else ""
            print(f"  {row.get('action')}: {row.get('elapsed_ms')}ms{cache}")

        print("\n=== Live Draft perf smoke: ALL PASS ===")
        return 0
    finally:
        for p in patches:
            p.stop()


if __name__ == "__main__":
    raise SystemExit(main())
