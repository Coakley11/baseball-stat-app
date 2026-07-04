"""Manual smoke checks for FLC deferred activation + Waiver Wire (headless session simulation)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from draft_archive_ui import (
    FANTASY_LINEUP_PAGE,
    FANTASY_STANDINGS_PAGE,
    schedule_fantasy_analysis_navigation,
)
from fantasy_league_context import (
    FANTASY_LEAGUE_CONTEXT_STATE_KEY,
    PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY,
    apply_fantasy_league_context_disk_state,
    apply_pending_league_context_activation,
    get_active_league_context,
    save_simulator_league_context,
)
from fantasy_waiver_wire import (
    GLOBAL_WAIVER_FILTER_KEY,
    build_waiver_pool,
    filter_unrostered_players,
    rostered_player_names,
)
from player_trade_context import TRADE_ACTION_ACQUIRE, start_trade_acquire_flow


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def _ok(label: str) -> None:
    print(f"PASS: {label}")


def _league_room() -> dict:
    return {
        "config": {"league_name": "Smoke League", "fantasy_format": "5x5 Roto", "your_team": "Daniel"},
        "rosters": {
            "Daniel": [{"fullName": "Aaron Judge", "Primary Position": "OF"}],
            "Rivals": [{"fullName": "Juan Soto", "Primary Position": "OF"}],
        },
        "draft_board": [
            {"Fantasy Team": "Daniel", "fullName": "Aaron Judge", "Pick": 1},
            {"Fantasy Team": "Rivals", "fullName": "Juan Soto", "Pick": 2},
        ],
    }


def check_mock_save_no_crash() -> None:
    session: dict = {"room_your_team": "Daniel"}
    board = pd.DataFrame(
        [
            {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1},
            {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2},
        ]
    )
    save_simulator_league_context(session, board, my_team_name="Daniel", defer_activation=True)
    if session.get("room_your_team") != "Daniel":
        _fail("defer save mutated room_your_team before apply")
    if PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY not in session:
        _fail("defer save did not schedule pending activation")
    apply_pending_league_context_activation(session)
    if session.get("room_your_team") != "Daniel":
        _fail("apply_pending did not set room_your_team")
    if get_active_league_context(session) is None:
        _fail("active context missing after apply_pending")
    _ok("1. Save Mock League Context — no room_your_team crash; activation on apply")


def check_library_nav() -> None:
    session: dict = {}
    board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1}])
    save_simulator_league_context(session, board, my_team_name="Daniel")
    session["room_your_team"] = "Stale"
    if not schedule_fantasy_analysis_navigation(session, FANTASY_STANDINGS_PAGE):
        _fail("schedule_fantasy_analysis_navigation returned False")
    apply_pending_league_context_activation(session)
    if session.get("_navigate_to_page") != FANTASY_STANDINGS_PAGE:
        _fail("standings navigation target missing")
    if session.get("room_your_team") != "Daniel":
        _fail("standings nav did not resync room_your_team")
    if not schedule_fantasy_analysis_navigation(session, FANTASY_LINEUP_PAGE):
        _fail("lineup navigation scheduling failed")
    _ok("2. Set Active + open Standings/Lineup — nav targets and team resync")


def check_waiver_filter_on_off() -> None:
    session: dict = {}
    board = pd.DataFrame(
        [
            {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1},
            {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2},
        ]
    )
    _, context = save_simulator_league_context(session, board, my_team_name="Daniel")
    pool = pd.DataFrame(
        [
            {"fullName": "Aaron Judge"},
            {"fullName": "Juan Soto"},
            {"fullName": "Mike Trout"},
        ]
    )
    waiver = build_waiver_pool(pool, context)
    if set(waiver["fullName"].astype(str)) != {"Mike Trout"}:
        _fail(f"waiver pool wrong: {set(waiver['fullName'].astype(str))}")
    session[GLOBAL_WAIVER_FILTER_KEY] = True
    filtered = filter_unrostered_players(session, pool, name_col="fullName")
    if set(filtered["fullName"].astype(str)) != {"Mike Trout"}:
        _fail(f"global filter ON wrong: {set(filtered['fullName'].astype(str))}")
    session[GLOBAL_WAIVER_FILTER_KEY] = False
    filtered_off = filter_unrostered_players(session, pool, name_col="fullName")
    if len(filtered_off) != 3:
        _fail(f"global filter OFF should return full pool, got {len(filtered_off)}")
    _ok("3–4. Waiver filter ON excludes rostered; OFF restores full universe")


def check_trade_handoff() -> None:
    session: dict = {}
    room = _league_room()
    save_simulator_league_context(
        session,
        pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Mike Trout", "Pick": 1},
                {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2},
            ]
        ),
        my_team_name="Daniel",
    )
    session["live_draft_room"] = room
    session["room_your_team"] = "Daniel"
    msg = start_trade_acquire_flow(session, player_name="Juan Soto", key_prefix="smoke")
    if not msg or "Opening Fantasy Lineup Assistant" not in msg:
        _fail(f"trade handoff message unexpected: {msg!r}")
    if session.get("_navigate_to_page") != FANTASY_LINEUP_PAGE:
        _fail("trade handoff navigation missing")
    apply_pending_league_context_activation(session)
    ctx = get_active_league_context(session)
    if ctx is None:
        _fail("trade handoff lost active context")
    _ok("5. Trade/Acquire handoff — deferred activation + navigation intact")


def check_persistence_after_refresh() -> None:
    session: dict = {}
    board = pd.DataFrame(
        [
            {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1},
            {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2},
        ]
    )
    save_simulator_league_context(session, board, my_team_name="Daniel")
    active_before = get_active_league_context(session)
    if active_before is None:
        _fail("no active context before disk round-trip")
    disk_state = {FANTASY_LEAGUE_CONTEXT_STATE_KEY: session.get(FANTASY_LEAGUE_CONTEXT_STATE_KEY)}
    restored: dict = {}
    apply_fantasy_league_context_disk_state(restored, disk_state)
    active_after = get_active_league_context(restored)
    if active_after is None:
        _fail("active context missing after disk restore")
    if active_after.get("league_context_id") != active_before.get("league_context_id"):
        _fail("league_context_id changed after restore")
    if len(rostered_player_names(active_after)) != 2:
        _fail("ownership not persisted after restore")
    _ok("6. Refresh/persistence — active context survives disk round-trip")


def main() -> None:
    print("FLC + Waiver Wire manual smoke (headless)")
    check_mock_save_no_crash()
    check_library_nav()
    check_waiver_filter_on_off()
    check_trade_handoff()
    check_persistence_after_refresh()
    print("ALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
