"""Manual smoke for Fantasy Trade Proposal System (headless session simulation)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from draft_archive_state import ACTIVE_DRAFT_ARCHIVE_KEY
from fantasy_league_context import (
    FANTASY_LEAGUE_CONTEXT_STATE_KEY,
    apply_fantasy_league_context_disk_state,
    build_ownership_map,
    get_active_league_context,
    save_simulator_league_context,
    set_active_league_context,
)
from fantasy_trade_proposals import (
    STALE_TRADE_MESSAGE,
    TRADE_PROPOSAL_STATUS_ACCEPTED,
    TRADE_PROPOSAL_STATUS_DECLINED,
    TRADE_PROPOSAL_STATUS_PENDING,
    accept_trade_proposal,
    consume_trade_proposal_handoff,
    create_trade_proposal,
    decline_trade_proposal,
    get_incoming_trade_proposals,
    get_outgoing_trade_proposals,
    recipient_view,
    set_trade_proposal_handoff,
)
from fantasy_waiver_wire import build_waiver_pool, rostered_player_names


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def _ok(label: str) -> None:
    print(f"PASS: {label}")


def _board() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Team": "Donny", "Player": "Player A", "Pick": 1},
            {"Team": "Team 2", "Player": "Player B", "Pick": 2},
        ]
    )


def main() -> None:
    print("Fantasy Trade Proposal manual smoke (headless)")
    session: dict = {}

    # 1. Set active league context
    entry, context = save_simulator_league_context(session, _board(), my_team_name="Donny")
    league_id = str(context.get("league_context_id") or "")
    if not league_id:
        _fail("no league context id after save")
    _ok("1. Active league context set (Donny)")

    # 2-6. Proposer creates trade
    proposal, err = create_trade_proposal(
        session,
        proposer_team="Donny",
        recipient_team="Team 2",
        proposer_gives=["Player A"],
        proposer_receives=["Player B"],
        verdict="Good for your team",
    )
    if err or not proposal:
        _fail(f"propose failed: {err}")
    pid = str(proposal["proposal_id"])
    _ok("2-6. Trade analyzed and proposed (Donny gives A, receives B)")

    # 7. Outgoing for Donny
    outgoing = get_outgoing_trade_proposals(session, "Donny")
    if not any(str(p.get("proposal_id")) == pid for p in outgoing):
        _fail("proposal missing from Donny outgoing")
    _ok("7. Appears in Donny Outgoing Trade Offers")

    # 8-9. Switch to Team 2 recipient context
    set_active_league_context(session, league_id)
    session["room_your_team"] = "Team 2"
    incoming = get_incoming_trade_proposals(session, "Team 2")
    if not any(str(p.get("proposal_id")) == pid for p in incoming):
        _fail("proposal missing from Team 2 incoming")
    _ok("8-9. Team 2 context — appears in Incoming Trade Offers")

    # 10-11. Analyze handoff reverses perspective
    set_trade_proposal_handoff(session, proposal_id=pid, view_as_team="Team 2")
    view = consume_trade_proposal_handoff(session)
    if view is None:
        _fail("handoff consume failed")
    if session.get("lineup_trade_give_players") != ["Player B"]:
        _fail(f"recipient give wrong: {session.get('lineup_trade_give_players')}")
    if session.get("lineup_trade_get_players") != ["Player A"]:
        _fail(f"recipient receive wrong: {session.get('lineup_trade_get_players')}")
    rv = recipient_view(incoming[0])
    if rv["give_players"] != ["Player B"] or rv["receive_players"] != ["Player A"]:
        _fail("recipient_view mismatch")
    _ok("10-11. Analyze This Trade reverses perspective (Team 2 gives B, receives A)")

    # 12-14. Accept trade
    accepted, err = accept_trade_proposal(session, pid)
    if err or not accepted:
        _fail(f"accept failed: {err}")
    if accepted.get("status") != TRADE_PROPOSAL_STATUS_ACCEPTED:
        _fail("status not accepted")
    ctx = get_active_league_context(session)
    if ctx is None:
        _fail("no context after accept")
    ownership = build_ownership_map(ctx)
    if ownership.get("player a", {}).get("owner_team") != "Team 2":
        _fail(f"Player A owner wrong: {ownership.get('player a')}")
    if ownership.get("player b", {}).get("owner_team") != "Donny":
        _fail(f"Player B owner wrong: {ownership.get('player b')}")
    _ok("12-14. Accept swaps rosters and rebuilds ownership_map")

    # 15. Waiver pool after accept
    pool = pd.DataFrame([{"Player": "Player A"}, {"Player": "Player B"}, {"Player": "Free Agent"}])
    waiver = build_waiver_pool(pool, ctx)
    names = set(waiver["Player"].astype(str))
    if "Player A" in names or "Player B" in names:
        _fail(f"rostered players in waiver pool: {names}")
    if "Free Agent" not in names:
        _fail("free agent missing from waiver pool")
    _ok("15. Waiver Wire pool correct after accepted trade")

    # 16-17. Second proposal + decline
    proposal2, err2 = create_trade_proposal(
        session,
        proposer_team="Donny",
        recipient_team="Team 2",
        proposer_gives=["Player B"],
        proposer_receives=["Player A"],
    )
    if err2 or not proposal2:
        _fail(f"second propose failed: {err2}")
    pid2 = str(proposal2["proposal_id"])
    before_decline = build_ownership_map(get_active_league_context(session) or {})
    declined, derr = decline_trade_proposal(session, pid2)
    if derr or not declined:
        _fail(f"decline failed: {derr}")
    if declined.get("status") != TRADE_PROPOSAL_STATUS_DECLINED:
        _fail("decline status wrong")
    after_decline = build_ownership_map(get_active_league_context(session) or {})
    if before_decline != after_decline:
        _fail("decline changed rosters")
    outgoing_d = get_outgoing_trade_proposals(session, "Donny")
    if not any(str(p.get("proposal_id")) == pid2 and p.get("status") == TRADE_PROPOSAL_STATUS_DECLINED for p in outgoing_d):
        _fail("declined status not in outgoing")
    _ok("16-17. Second proposal declined — rosters unchanged, status updated")

    # 18. Disk restore
    disk = {
        FANTASY_LEAGUE_CONTEXT_STATE_KEY: session.get(FANTASY_LEAGUE_CONTEXT_STATE_KEY),
        ACTIVE_DRAFT_ARCHIVE_KEY: session.get(ACTIVE_DRAFT_ARCHIVE_KEY),
    }
    restored: dict = {}
    apply_fantasy_league_context_disk_state(restored, disk)
    r_out = get_outgoing_trade_proposals(restored, "Donny")
    statuses = {str(p.get("proposal_id")): p.get("status") for p in r_out}
    if statuses.get(pid) != TRADE_PROPOSAL_STATUS_ACCEPTED:
        _fail(f"accepted proposal not restored: {statuses}")
    if statuses.get(pid2) != TRADE_PROPOSAL_STATUS_DECLINED:
        _fail(f"declined proposal not restored: {statuses}")
    _ok("18. Proposals/statuses survive disk restore")

    # Stale case
    session2: dict = {}
    save_simulator_league_context(session2, _board(), my_team_name="Donny")
    stale_prop, _ = create_trade_proposal(
        session2,
        proposer_team="Donny",
        recipient_team="Team 2",
        proposer_gives=["Player A"],
        proposer_receives=["Player B"],
    )
    assert stale_prop is not None
    stale_pid = str(stale_prop["proposal_id"])
    from fantasy_league_context import get_league_context, upsert_league_context

    ctx2 = get_active_league_context(session2)
    assert ctx2 is not None
    lid = str(ctx2.get("league_context_id") or "")
    loaded = get_league_context(session2, lid)
    assert loaded is not None
    rosters = loaded.get("league_rosters") or {}
    team2 = dict(rosters.get("Team 2") or {})
    players = [dict(p) for p in (team2.get("players") or []) if isinstance(p, dict)]
    team2["players"] = [p for p in players if str(p.get("player_name")) != "Player B"]
    rosters["Team 2"] = team2
    loaded["league_rosters"] = rosters
    upsert_league_context(session2, loaded)
    stale_accept, stale_err = accept_trade_proposal(session2, stale_pid)
    if stale_accept is not None:
        _fail("stale accept should have failed")
    if stale_err != STALE_TRADE_MESSAGE:
        _fail(f"stale message wrong: {stale_err!r}")
    _ok("Stale case — accept blocked with expected message")

    print("ALL TRADE PROPOSAL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
