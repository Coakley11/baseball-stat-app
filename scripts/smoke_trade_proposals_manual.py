"""Manual smoke for Fantasy Trade Proposal Phase 1 + Phase 2 (headless session simulation)."""

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
    LINEUP_ASSISTANT_PAGE,
    apply_fantasy_league_context_disk_state,
    build_ownership_map,
    get_active_league_context,
    save_simulator_league_context,
    set_active_league_context,
)
from fantasy_trade_proposals import (
    STALE_TRADE_MESSAGE,
    TRADE_PROPOSAL_STATUS_ACCEPTED,
    TRADE_PROPOSAL_STATUS_CANCELED,
    TRADE_PROPOSAL_STATUS_DECLINED,
    TRADE_PROPOSAL_STATUS_PENDING,
    accept_trade_proposal,
    cancel_trade_proposal,
    consume_trade_proposal_handoff,
    create_trade_proposal,
    decline_trade_proposal,
    get_incoming_trade_proposals,
    get_outgoing_trade_proposals,
    get_trade_notifications,
    navigate_to_trade_proposal,
    recipient_view,
)
from fantasy_waiver_wire import build_waiver_pool, get_league_activity, rostered_player_names


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
    print("Fantasy Trade Proposal Phase 2 manual smoke (headless)")
    session: dict = {}

    # 1. Set active league context
    _, context = save_simulator_league_context(session, _board(), my_team_name="Donny")
    league_id = str(context.get("league_context_id") or "")
    if not league_id:
        _fail("no league context id after save")
    _ok("1. Active league context set")

    # 2. Propose trade Donny → Team 2
    proposal, err = create_trade_proposal(
        session,
        proposer_team="Donny",
        recipient_team="Team 2",
        proposer_gives=["Player A"],
        proposer_receives=["Player B"],
    )
    if err or not proposal:
        _fail(f"propose failed: {err}")
    pid = str(proposal["proposal_id"])
    _ok("2. Trade proposed Donny to Team 2")

    # 3. Team 2 sidebar alert
    session["room_your_team"] = "Team 2"
    alerts_t2 = get_trade_notifications(session, "Team 2")
    if not any(a.get("kind") == "incoming" and a.get("proposal_id") == pid for a in alerts_t2):
        _fail(f"Team 2 missing incoming alert: {alerts_t2}")
    _ok("3. Team 2 sees League Trade Alert")

    # 4-6. Click alert deep-link loads proposal in Trade Analyzer
    alert = next(a for a in alerts_t2 if a.get("proposal_id") == pid)
    navigate_to_trade_proposal(
        session,
        proposal_id=pid,
        view_as_team="Team 2",
        alert_key=str(alert.get("alert_key") or ""),
    )
    if session.get("_navigate_to_page") != LINEUP_ASSISTANT_PAGE:
        _fail("deep-link did not target Lineup Assistant")
    view = consume_trade_proposal_handoff(session)
    if view is None:
        _fail("handoff consume failed")
    _ok("4-6. Alert deep-links to Trade Analyzer with correct proposal")

    # 7. Recipient perspective
    if session.get("lineup_trade_give_players") != ["Player B"]:
        _fail(f"recipient give wrong: {session.get('lineup_trade_give_players')}")
    if session.get("lineup_trade_get_players") != ["Player A"]:
        _fail(f"recipient receive wrong: {session.get('lineup_trade_get_players')}")
    incoming = get_incoming_trade_proposals(session, "Team 2")
    rv = recipient_view(incoming[0])
    if rv["give_players"] != ["Player B"] or rv["receive_players"] != ["Player A"]:
        _fail("recipient_view mismatch")
    _ok("7. Recipient perspective correct (Team 2 gives B, receives A)")

    # 8-9. Accept + rosters/ownership
    accepted, aerr = accept_trade_proposal(session, pid)
    if aerr or not accepted:
        _fail(f"accept failed: {aerr}")
    ctx = get_active_league_context(session)
    if ctx is None:
        _fail("no context after accept")
    ownership = build_ownership_map(ctx)
    if ownership.get("player a", {}).get("owner_team") != "Team 2":
        _fail("Player A not on Team 2 after accept")
    if ownership.get("player b", {}).get("owner_team") != "Donny":
        _fail("Player B not on Donny after accept")
    _ok("8-9. Accept updates rosters and ownership_map")

    # 10. League activity summary
    activity = get_league_activity(ctx)
    summaries = [str(a.get("summary") or "") for a in activity]
    if not any("Donny traded Player A to Team 2 for Player B" in s for s in summaries):
        _fail(f"league activity missing summary: {summaries}")
    _ok('10. League Activity shows "Donny traded Player A to Team 2 for Player B."')

    # 11-14. Second proposal + cancel + recipient cannot accept + disk restore
    session["room_your_team"] = "Donny"
    prop2, err2 = create_trade_proposal(
        session,
        proposer_team="Donny",
        recipient_team="Team 2",
        proposer_gives=["Player B"],
        proposer_receives=["Player A"],
    )
    if err2 or not prop2:
        _fail(f"second propose failed: {err2}")
    pid2 = str(prop2["proposal_id"])
    canceled, cerr = cancel_trade_proposal(session, pid2, canceled_by_team="Donny")
    if cerr or not canceled:
        _fail(f"cancel failed: {cerr}")
    if canceled.get("status") != TRADE_PROPOSAL_STATUS_CANCELED:
        _fail("cancel status wrong")
    session["room_your_team"] = "Team 2"
    accepted2, err_accept2 = accept_trade_proposal(session, pid2)
    if accepted2 is not None:
        _fail("recipient accepted canceled trade")
    if "no longer pending" not in str(err_accept2).lower():
        _fail(f"unexpected cancel accept error: {err_accept2}")
    disk_cancel = {FANTASY_LEAGUE_CONTEXT_STATE_KEY: session.get(FANTASY_LEAGUE_CONTEXT_STATE_KEY)}
    restored_cancel: dict = {}
    apply_fantasy_league_context_disk_state(restored_cancel, disk_cancel)
    r_in = get_incoming_trade_proposals(restored_cancel, "Team 2")
    restored_p2 = next((p for p in r_in if str(p.get("proposal_id")) == pid2), None)
    if not restored_p2 or restored_p2.get("status") != TRADE_PROPOSAL_STATUS_CANCELED:
        _fail("canceled status not restored from disk")
    _ok("11-14. Cancel Offer works; recipient cannot accept; canceled survives disk restore")

    # 15-17. Third proposal + decline + proposer alert + cannot accept later
    session["room_your_team"] = "Donny"
    prop3, err3 = create_trade_proposal(
        session,
        proposer_team="Donny",
        recipient_team="Team 2",
        proposer_gives=["Player B"],
        proposer_receives=["Player A"],
    )
    if err3 or not prop3:
        _fail(f"third propose failed: {err3}")
    pid3 = str(prop3["proposal_id"])
    session["room_your_team"] = "Team 2"
    declined, derr = decline_trade_proposal(session, pid3)
    if derr or not declined:
        _fail(f"decline failed: {derr}")
    session["room_your_team"] = "Donny"
    alerts_donny = get_trade_notifications(session, "Donny")
    if not any(a.get("kind") == "declined" and a.get("proposal_id") == pid3 for a in alerts_donny):
        _fail(f"Donny missing declined alert: {alerts_donny}")
    accepted3, err_accept3 = accept_trade_proposal(session, pid3)
    if accepted3 is not None:
        _fail("declined trade was accepted")
    if "no longer pending" not in str(err_accept3).lower():
        _fail(f"unexpected decline accept error: {err_accept3}")
    _ok("15-17. Decline works; proposer sees declined alert; cannot accept later")

    # 18. Accepted trade cannot be canceled
    canceled_acc, cerr_acc = cancel_trade_proposal(session, pid, canceled_by_team="Donny")
    if canceled_acc is not None:
        _fail("accepted trade was canceled")
    if "pending" not in str(cerr_acc).lower():
        _fail(f"unexpected accepted cancel error: {cerr_acc}")
    _ok("18. Accepted trade cannot be canceled")

    # 19. Notifications scoped to active league/team
    if get_trade_notifications(session, "Rivals"):
        _fail("notifications leaked to unrelated team")
    if not get_trade_notifications(session, "Donny"):
        _fail("Donny should have declined alert")
    _ok("19. Notifications scoped to active league/team only")

    # Stale case (bonus)
    session_stale: dict = {}
    save_simulator_league_context(session_stale, _board(), my_team_name="Donny")
    stale_prop, _ = create_trade_proposal(
        session_stale,
        proposer_team="Donny",
        recipient_team="Team 2",
        proposer_gives=["Player A"],
        proposer_receives=["Player B"],
    )
    assert stale_prop is not None
    from fantasy_league_context import get_league_context, upsert_league_context

    loaded = get_league_context(session_stale, str(get_active_league_context(session_stale)["league_context_id"]))
    assert loaded is not None
    rosters = loaded.get("league_rosters") or {}
    team2 = dict(rosters.get("Team 2") or {})
    team2["players"] = [
        p for p in (team2.get("players") or [])
        if isinstance(p, dict) and str(p.get("player_name")) != "Player B"
    ]
    rosters["Team 2"] = team2
    loaded["league_rosters"] = rosters
    upsert_league_context(session_stale, loaded)
    stale_accept, stale_err = accept_trade_proposal(session_stale, str(stale_prop["proposal_id"]))
    if stale_accept is not None or stale_err != STALE_TRADE_MESSAGE:
        _fail(f"stale case failed: {stale_err!r}")
    _ok("Stale case — accept blocked with expected message")

    print("ALL TRADE PROPOSAL PHASE 2 SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
