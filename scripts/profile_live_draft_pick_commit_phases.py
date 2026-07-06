#!/usr/bin/env python3
"""Phase-level profile for commit_manual_live_pick on the real Lahman player pool.

Run from repo root:
  python scripts/profile_live_draft_pick_commit_phases.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd


def _load_real_pool(session: dict) -> pd.DataFrame:
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
    return pool.copy()


def _build_room(pool: pd.DataFrame) -> dict:
    teams = ["Daniel", "Rival A", "Rival B", "Rival C"]
    return {
        "status": "in_progress",
        "current_pick_index": 0,
        "draft_room_id": "profile-real-pool",
        "config": {
            "num_teams": 4,
            "picks_per_team": 15,
            "fantasy_format": "5x5 Roto",
            "scoring_type": "Roto (5x5)",
            "your_team": "Daniel",
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


def main() -> int:
    from live_draft_perf import PHASE_PICK_COMMIT, pick_commit_phase_total_ms, summarize_pick_commit_phases
    from live_draft_pick_commit import commit_manual_live_pick
    from live_draft_state import LIVE_DRAFT_ROOM_KEY, LIVE_DRAFT_STATE_KEY, prepare_live_draft_state, room_to_persist_dict

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

    print("Loading real player pool...")
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
        player_row = pool.iloc[0].to_dict()

        t_wall = time.perf_counter()
        commit = commit_manual_live_pick(session, room, player_row, source="profile_manual")
        wall_ms = (time.perf_counter() - t_wall) * 1000.0

        if not commit.ok:
            print(f"FAIL: pick commit failed: {commit.message}")
            return 1

        phases = summarize_pick_commit_phases(session, limit=24)
        outer = float(session.get("_page_perf_ns", {}).get("timings", {}).get(PHASE_PICK_COMMIT) or 0) * 1000.0

        print(f"\n=== Pick commit phase profile (real pool, n={len(pool)}) ===")
        print(f"Wall clock: {wall_ms:.1f} ms")
        if outer:
            print(f"Outer pick_commit wrapper: {outer:.1f} ms")
        print(f"Instrumented sub-phases total: {pick_commit_phase_total_ms(session):.1f} ms")
        print("\nPhase breakdown (descending):")
        for name, ms in phases:
            bar = "#" * min(40, int(ms / 10))
            print(f"  {name:42} {ms:8.1f} ms  {bar}")

        if wall_ms < 300:
            print(f"\nTarget met: draft player {wall_ms:.0f} ms < 300 ms")
        else:
            print(f"\nTarget missed: draft player {wall_ms:.0f} ms (goal < 300 ms)")

        return 0
    finally:
        for p in patches:
            p.stop()


if __name__ == "__main__":
    raise SystemExit(main())
