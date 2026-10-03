"""Deterministic Fantasy league fixture for mobile/browser verification (Mobile M4).

    python scripts/mobile_fantasy_fixture.py

Seeds the local ``test_user`` workspace (open the app with ``?suite_workspace=test_user``)
through production code paths only — no hand-written state:

1. A 6-team x 12-round Solo Live Draft over the real prewarmed unified pool, every pick
   made by ``expire_current_pick_and_advance`` (the production timer-expiry autopick).
2. ``save_imported_league_context(assign_team=True)`` — real_league + library archive,
   activated, "Dingers" claimed by this local account.
3. ``claim_team_in_league_context`` — a second account claims "Bat Flips" (trades need two
   distinct owners).
4. ``save_league_lineup_format`` — 8 starters, 12-man roster capacity (4 bench).
5. ``force_save_baseball_state`` — the app's own workspace save.

Also writes ``data/tb_probe/mobile_fantasy_current_stats.csv`` (the pool's latest-season
lines) for the Standings page's **Upload CSV** source, so standings/waiver/lineup stats are
deterministic and offline. Requires ``data/tb_probe/prewarm_unified_pool.parquet``
(written by the prewarm step in ``scripts/local_tb_lifecycle_accept.py``). Local only: refuses to run when Supabase /
auth secrets are configured. Everything written is gitignored or untracked runtime data.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "data" / "tb_probe" / "prewarm_unified_pool.parquet"
STATS_CSV = ROOT / "data" / "tb_probe" / "mobile_fantasy_current_stats.csv"
SHARED_STORE = ROOT / "data" / "tb_probe" / "mobile_fantasy_shared_store"
WORKSPACE = "test_user"
TEAMS = ["Dingers", "Bat Flips", "Moonshots", "Southpaws", "Grand Salamis", "Walk-Offs"]
MY_TEAM, RIVAL_TEAM = "Dingers", "Bat Flips"
SLOTS = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "UTIL": 1, "DH": 0, "P": 0, "BN": 3}
LINEUP = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]
_APP_FLAG = "MOBILE_FANTASY_FIXTURE_APP"


def _seed_app() -> None:
    """Body executed inside the Streamlit runtime (AppTest)."""
    import pandas as pd
    import streamlit as st

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    from suite_workspace import get_active_workspace_id, init_suite_workspace

    if init_suite_workspace(st) != WORKSPACE:
        st.write("ABORT: workspace is not test_user")
        st.stop()
    from baseball_persistent_state import apply_baseball_session_defaults, force_save_baseball_state
    from live_draft_canonical_snapshot import begin_live_draft_paint, invalidate_live_draft_paint
    from live_draft_solo_timer import expire_current_pick_and_advance
    from live_draft_timer_logic import live_draft_reset_timer
    from tests.live_draft_accelerated_harness import noop_persist

    apply_baseball_session_defaults(st)
    rounds = sum(SLOTS.values())
    pool = pd.read_parquet(POOL).reset_index(drop=True)
    order, n = [], 1
    for rnd in range(1, rounds + 1):
        for team in TEAMS if rnd % 2 else list(reversed(TEAMS)):
            order.append({"Pick": n, "Round": rnd, "Team": team})
            n += 1
    room = {
        "draft_room_id": "MOBILE-FANTASY-FIXTURE", "status": "in_progress", "current_pick_index": 0,
        "teams": TEAMS, "pick_order": order, "draft_board": [], "drafted_player_ids": [],
        "rosters": {t: [] for t in TEAMS}, "revision": 1, "meta": {"sync": {"revision": 1}},
        "config": {
            "league_name": "Mobile Fixture League", "num_teams": len(TEAMS), "team_count": len(TEAMS),
            "picks_per_team": rounds, "rounds": rounds, "timer_seconds": 30, "teams": TEAMS,
            "your_team": MY_TEAM, "user_team": MY_TEAM, "draft_setup_mode": "solo",
            "auto_pick_rule": "balanced recommendation", "queue_auto_pick": False,
            "fantasy_format": "5x5 Roto", "scoring_type": "5x5 Roto", "slots": SLOTS,
        },
        "pool": pool,
    }
    live_draft_reset_timer(room)
    session = {"live_draft_setup_mode": "solo", "live_draft_room": room, "draft_queue": []}
    begin_live_draft_paint(session, room, state_source="mobile_fixture_start")
    with noop_persist():  # no draft-room file / autosave during the synthetic clock
        while str(room.get("status") or "") != "complete":
            room["timer_deadline"] = time.time() - 0.05
            res = expire_current_pick_and_advance(room, session=session)
            if not res.ok:
                st.write(f"ABORT: pick failed {res}")
                st.stop()
            invalidate_live_draft_paint(session)
            begin_live_draft_paint(session, room, state_source="mobile_fixture_pick")

    from fantasy_league_context import get_active_league_context, save_imported_league_context
    from fantasy_league_lineup_format import (
        configuration_source_for_context,
        roster_capacity_from_format,
        save_league_lineup_format,
    )
    from fantasy_league_team_ownership import claim_team_in_league_context, trades_enabled
    from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store

    SHARED_STORE.mkdir(parents=True, exist_ok=True)
    set_shared_league_store(LocalFileSharedLeagueStore(root=SHARED_STORE))
    board = pd.DataFrame([
        {"Pick": i + 1, "Team": str(b.get("Team") or ""), "Player": str(b.get("fullName") or ""),
         "playerID": str(b.get("playerID") or ""), "Primary Position": str(b.get("Primary Position") or "")}
        for i, b in enumerate(room["draft_board"])
    ])
    cfg = {"fantasy_format": "5x5 Roto", "scoring_type": "5x5 Roto", "slots": SLOTS, "slot_instances": [],
           "league_name": "Mobile Fixture League", "team_count": len(TEAMS), "rounds": rounds}
    _entry, ctx = save_imported_league_context(
        st.session_state, board, my_team_name=MY_TEAM, draft_name="Mobile Fixture League",
        league_name="Mobile Fixture League", config=cfg, assign_team=True,
    )
    lcid = str(ctx.get("league_context_id"))
    _ctx2, err = claim_team_in_league_context(
        st.session_state, lcid, RIVAL_TEAM, user_id="local:mobile-fixture-rival", display_name="Fixture Rival"
    )
    fmt = save_league_lineup_format(
        st.session_state, lineup_slots=LINEUP, roster_capacity=rounds, configured_by="commissioner",
        configuration_source=configuration_source_for_context(get_active_league_context(st.session_state)),
    )
    ctx = get_active_league_context(st.session_state) or ctx
    st.session_state["standings_scoring_format"] = "5x5 Roto"
    force_save_baseball_state(st, reason="mobile_fantasy_fixture")
    st.write(
        f"OK picks={len(room['draft_board'])} context={lcid} type={ctx.get('context_type')} "
        f"my_team={ctx.get('my_team_name')!r} rival_claim_err={err!r} format_ok={fmt.get('ok')} "
        f"capacity={roster_capacity_from_format(ctx)} trades={trades_enabled(ctx, st.session_state)} "
        f"workspace={get_active_workspace_id(st)}"
    )


def main() -> int:
    if not POOL.is_file():
        print(f"Missing {POOL} — run the prewarm step in scripts/local_tb_lifecycle_accept.py first.")
        return 1
    if (ROOT / ".streamlit" / "secrets.toml").is_file() or any(
        os.environ.get(k) for k in ("SUPABASE_URL", "SUITE_AUTH_ENABLED", "SUITE_USER_ID")
    ):
        print("Refusing to run: cloud/auth configuration detected. This fixture is local-only.")
        return 1
    import pandas as pd
    from streamlit.testing.v1 import AppTest

    cols = {"fullName": "Name", "Team": "Team", "Primary Position": "Pos", "latest_HR": "HR",
            "latest_RBI": "RBI", "latest_R": "R", "latest_SB": "SB", "latest_BA": "BA",
            "latest_OBP": "OBP", "latest_SLG": "SLG", "latest_OPS": "OPS", "latest_H": "H", "latest_BB": "BB"}
    pool = pd.read_parquet(POOL)
    pool[[c for c in cols if c in pool.columns]].rename(columns=cols).to_csv(STATS_CSV, index=False)
    print(f"Stats CSV: {STATS_CSV}")
    os.environ[_APP_FLAG] = "1"
    at = AppTest.from_file(str(Path(__file__).resolve()), default_timeout=900)
    at.query_params["suite_workspace"] = WORKSPACE
    at.run()
    for exc in at.exception:
        print("EXCEPTION:", exc.value)
    for md in at.markdown:
        print(md.value)
    return 0 if any(str(md.value).startswith("OK ") for md in at.markdown) else 1


if os.environ.get(_APP_FLAG) == "1":
    _seed_app()
elif __name__ == "__main__":
    sys.exit(main())
