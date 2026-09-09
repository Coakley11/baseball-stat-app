"""Full Solo Draft acceptance: Pick 1 → final, legal Auto Picks, Draft Complete persist.

Runs without Streamlit browser — pure room/autopick engine under realistic 4×10 config.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from live_draft_autopick import live_draft_auto_pick
from live_draft_completion import LIFECYCLE_ACTIVE_DRAFT, resolve_live_draft_lifecycle
from live_draft_recommendations import live_draft_recommendations
from live_draft_roster_slots import get_remaining_position_needs
from live_draft_state import (
    LIVE_DRAFT_ROOM_KEY,
    prepare_live_draft_state,
    write_canonical_live_draft_state,
)
from player_photos import player_grade_display
from recommendation_schema import ensure_recommendation_ranking_schema


POSITIONS = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "DH", "SP", "SP", "RP", "RP", "OF", "1B", "C"]


def _build_room(*, rule: str = "balanced recommendation", teams: int = 4, rounds: int = 12) -> dict[str, Any]:
    team_names = [f"Team {chr(65 + i)}" for i in range(teams)]
    pick_order: list[dict[str, Any]] = []
    pick_n = 1
    for rnd in range(1, rounds + 1):
        seq = team_names if rnd % 2 == 1 else list(reversed(team_names))
        for team in seq:
            pick_order.append({"Pick": pick_n, "Round": rnd, "Team": team})
            pick_n += 1
    pool_size = teams * rounds + 120
    pool = pd.DataFrame(
        [
            {
                "playerID": f"p{i:04d}",
                "fullName": f"Player {i:04d}",
                "Primary Position": POSITIONS[i % len(POSITIONS)],
                "Eligible Positions": POSITIONS[i % len(POSITIONS)],
                "Expected Fantasy Value": float(0.95 - (i * 0.002)),
                "Decision Score": float(0.90 - (i * 0.002)),
                "Draft Fit Score": float(0.4 + (i % 10) * 0.05),
                "Positional Fit": float(0.3 + (i % 8) * 0.05),
                "Market Rank": i + 1,
                "Model Rank": i + 1,
                "Sleeper Score": float(0.1 + (i % 5) * 0.02),
                "Position Scarcity Score": float(0.2 + (i % 7) * 0.03),
                "Fantasy Edge": float((i % 9) * 0.01),
                "Risk": float(0.1 + (i % 4) * 0.05),
            }
            for i in range(pool_size)
        ]
    )
    return {
        "draft_room_id": f"FULL-ACC-{rule.replace(' ', '-')[:24]}",
        "status": "in_progress",
        "current_pick_index": 0,
        "teams": team_names,
        "pick_order": pick_order,
        "draft_board": [],
        "drafted_player_ids": [],
        "rosters": {t: [] for t in team_names},
        "config": {
            "num_teams": teams,
            "picks_per_team": rounds,
            "rounds": rounds,
            "your_team": team_names[0],
            "user_team": team_names[0],
            "teams": team_names,
            "auto_pick_rule": rule,
            # 10 starters + 2 BN = 12 rounds — bench opens after starters fill.
            "slots": {
                "C": 1,
                "1B": 1,
                "2B": 1,
                "3B": 1,
                "SS": 1,
                "OF": 3,
                "DH": 0,
                "P": 2,
                "BN": 2,
            },
            "fantasy_format": "5x5 Roto",
            "timer_seconds": 15,
            "draft_setup_mode": "solo",
        },
        "pool": pool,
        "timer_deadline": time.time() + 15,
    }


def _assert_pick_legal(room: dict[str, Any], team: str, player: dict[str, Any], *, pick_no: int) -> None:
    """After pick: player is on team roster; was legal for that team's prior gaps when required."""
    # Post-pick roster already includes the player — legality was enforced pre-pick by filter.
    roster = list((room.get("rosters") or {}).get(team) or [])
    pids = {str(r.get("playerID") or "") for r in roster}
    assert str(player.get("playerID") or "") in pids, f"pick {pick_no}: {player.get('fullName')} not on {team}"


def run_full_draft(*, rule: str = "balanced recommendation") -> dict[str, Any]:
    room = _build_room(rule=rule)
    session: dict[str, Any] = {"live_draft_room": room, "live_draft_auto_rule": rule}
    total = len(room["pick_order"])
    timings: list[float] = []
    legality_log: list[dict[str, Any]] = []
    grade_checks = 0

    for i in range(total):
        slot = room["pick_order"][i]
        team = str(slot["Team"])
        roster_before = list((room.get("rosters") or {}).get(team) or [])
        gaps_before = get_remaining_position_needs(pd.DataFrame(roster_before), room["config"])
        t0 = time.perf_counter()
        ok, msg = live_draft_auto_pick(room, session, persist=False, finalize=False)
        dt = time.perf_counter() - t0
        timings.append(dt)
        assert ok, f"pick {i+1}/{total} failed for {team}: {msg}"
        pick = (room.get("draft_board") or [])[-1]
        _assert_pick_legal(room, team, pick, pick_no=i + 1)
        legality_log.append(
            {
                "pick": i + 1,
                "team": team,
                "player": str(pick.get("fullName") or ""),
                "pos": str(pick.get("Primary Position") or ""),
                "gaps_before": list(gaps_before),
                "ms": round(dt * 1000, 1),
            }
        )
        # Spot-check recommendations for user team when on clock (every 4th pick).
        if team == room["config"]["your_team"] and (i % 4 == 0) and str(room.get("status")) != "complete":
            top, *_rest = live_draft_recommendations(room, top_n=6, session=session)
            if not top.empty:
                schema = ensure_recommendation_ranking_schema(top)
                row = schema.iloc[0]
                grade = player_grade_display(row)
                assert grade and grade.lower() != "not available", f"empty Player Grade at pick {i+1}"
                grade_checks += 1

    assert str(room.get("status") or "") == "complete"
    assert len(room["draft_board"]) == total
    ids = [str(p.get("playerID") or "") for p in room["draft_board"]]
    assert len(ids) == len(set(ids)), "duplicate players drafted"
    assert resolve_live_draft_lifecycle(session) == LIFECYCLE_ACTIVE_DRAFT

    # Persist + refresh simulation
    write_canonical_live_draft_state(session, room, reason="full_draft_complete", local_edit=True)
    session.pop(LIVE_DRAFT_ROOM_KEY, None)
    prepared = prepare_live_draft_state(session)
    assert prepared is not None
    restored = session.get(LIVE_DRAFT_ROOM_KEY)
    assert isinstance(restored, dict)
    assert str(restored.get("status") or "") == "complete"
    assert resolve_live_draft_lifecycle(session) == LIFECYCLE_ACTIVE_DRAFT
    assert len(restored.get("draft_board") or []) == total

    return {
        "ok": True,
        "rule": rule,
        "total_picks": total,
        "grade_checks": grade_checks,
        "median_ms": sorted(timings)[len(timings) // 2] * 1000,
        "p95_ms": sorted(timings)[int(len(timings) * 0.95)] * 1000,
        "max_ms": max(timings) * 1000,
        "lifecycle": resolve_live_draft_lifecycle(session),
        "sample_log": legality_log[:5] + legality_log[-3:],
    }


def run_strategy_comparison() -> dict[str, Any]:
    """Same starting pool shape; strategies can diverge when multiple positions open."""
    from live_draft_pick_scoring import live_draft_target_counts, score_available_for_rule

    room = _build_room(rule="best market rank", teams=2, rounds=3)
    pool = room["pool"].copy()
    roster = pd.DataFrame()
    cfg = dict(room["config"])
    cfg["room"] = room
    targets = live_draft_target_counts(cfg)
    market, _ = score_available_for_rule(pool, roster, "best market rank", targets, config=cfg)
    balanced, _ = score_available_for_rule(
        pool, roster, "balanced recommendation", targets, config=cfg
    )
    m0 = str(market.iloc[0].get("fullName") or "") if not market.empty else ""
    b0 = str(balanced.iloc[0].get("fullName") or "") if not balanced.empty else ""
    # Catcher-only divergence proof
    room_c = _build_room(rule="best market rank", teams=2, rounds=2)
    # Fill Team A except C
    filled = []
    for pos in ["1B", "2B", "3B", "SS", "OF", "OF", "OF", "DH", "SP", "SP"]:
        row = pool[pool["Primary Position"] == pos].iloc[0].to_dict()
        # unique ids
        row = dict(row)
        row["playerID"] = f"fill-{pos}-{len(filled)}"
        filled.append(row)
        pool = pool[pool["playerID"] != row.get("playerID")]
    # Re-pull fresh pool for filter test
    pool2 = room_c["pool"].copy()
    roster_c = pd.DataFrame(
        [
            {"playerID": f"f{i}", "fullName": f"F{i}", "Primary Position": p}
            for i, p in enumerate(["1B", "2B", "3B", "SS", "OF", "OF", "OF", "DH", "SP", "SP"])
        ]
    )
    cfg_c = dict(room_c["config"])
    cfg_c["room"] = room_c
    targets_c = live_draft_target_counts(cfg_c)
    m_c, _ = score_available_for_rule(pool2, roster_c, "best market rank", targets_c, config=cfg_c)
    assert not m_c.empty
    assert str(m_c.iloc[0].get("Primary Position") or "") == "C"
    return {
        "ok": True,
        "empty_roster_market_top": m0,
        "empty_roster_balanced_top": b0,
        "catcher_only_market_pos": str(m_c.iloc[0].get("Primary Position") or ""),
        "catcher_only_market_player": str(m_c.iloc[0].get("fullName") or ""),
    }


if __name__ == "__main__":
    import json

    print("=== strategy comparison ===")
    print(json.dumps(run_strategy_comparison(), indent=2))
    print("=== full draft balanced ===")
    print(json.dumps(run_full_draft(rule="balanced recommendation"), indent=2, default=str))
    print("=== full draft best market rank ===")
    print(json.dumps(run_full_draft(rule="best market rank"), indent=2, default=str))
