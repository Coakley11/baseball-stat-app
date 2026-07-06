#!/usr/bin/env python3
"""Programmatic Live Draft Room perf baseline (Developer Mode timings simulation).

Run from repo root:
  python scripts/profile_live_draft_baseline.py

Simulates the Live Draft hot path without loading streamlit_app.
Table render times approximate dataframe prep (Streamlit render excluded).
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd


def _sample_room(*, pool_size: int = 40) -> dict:
    rows = []
    for i in range(pool_size):
        rows.append(
            {
                "playerID": f"p{i}",
                "fullName": f"Player {i}",
                "Primary Position": "OF" if i % 3 else "SP",
                "Expected Fantasy Value": 80.0 - i * 0.5,
                "Model Rank": i + 1,
                "Market Rank": i + 1,
            }
        )
    pool = pd.DataFrame(rows)
    teams = ["Daniel", "Rival A", "Rival B", "Rival C"]
    return {
        "status": "in_progress",
        "current_pick_index": 0,
        "draft_room_id": "baseline-room",
        "config": {
            "num_teams": 4,
            "picks_per_team": 10,
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
            for j, t in enumerate(teams * 10)
        ],
        "draft_board": [],
        "rosters": {t: [] for t in teams},
        "drafted_player_ids": [],
        "pool": pool,
    }


def _target_counts(cfg: dict) -> dict[str, int]:
    keys = ("slot_c", "slot_1b", "slot_2b", "slot_3b", "slot_ss", "slot_of", "slot_dh", "slot_p", "slot_bench")
    return {k: int(cfg.get(k) or 0) for k in keys}


def _build_board_df(room: dict) -> pd.DataFrame:
    if not room.get("draft_board"):
        return pd.DataFrame()
    df = pd.DataFrame(room["draft_board"])
    rename = {"fullName": "Player", "Team": "MLB Team", "Fantasy Team": "Draft Team"}
    for old, new in rename.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})
    show = [
        "Round", "Pick", "Draft Team", "Player", "Primary Position", "MLB Team",
        "Expected Fantasy Value", "Model Rank", "Market Rank", "Fantasy Edge", "Pick Verdict",
    ]
    return df[[c for c in show if c in df.columns]]


def _prep_rec_table(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "fullName", "Primary Position", "Expected Fantasy Value", "Model Rank", "Market Rank",
        "Fantasy Edge", "Draft Fit Score", "Decision Score",
    ]
    out = df[[c for c in cols if c in df.columns]].copy()
    return out.rename(columns={"fullName": "Player"})


def _cache_summary(audit: list) -> dict[str, dict[str, int]]:
    totals: Counter[str] = Counter()
    hits: Counter[str] = Counter()
    for row in audit:
        label = str(row.get("label") or "")
        totals[label] += 1
        if row.get("hit"):
            hits[label] += 1
    return {
        label: {"hit": hits[label], "miss": totals[label] - hits[label], "total": totals[label]}
        for label in sorted(totals)
    }


def _phase_ms(timings: dict, phase: str) -> float | None:
    val = timings.get(phase)
    return round(float(val) * 1000.0, 2) if val is not None else None


def _action_ms(actions: list, *, phase: str = "", action: str = "", cache: str = "") -> list[float]:
    out: list[float] = []
    for row in actions:
        if phase and row.get("phase") != phase:
            continue
        if action and row.get("action") != action:
            continue
        if cache and row.get("cache") != cache:
            continue
        out.append(float(row.get("elapsed_ms") or 0.0))
    return out


def _run_baseline(*, pool_size: int = 40) -> dict:
    from draft_state import add_player_to_draft_queue, remove_player_from_draft_queue
    from live_draft_category_outlook import compute_category_outlook
    from live_draft_perf import (
        PHASE_BOARD_TABLE,
        PHASE_DECISION_CONTEXT,
        PHASE_DRAFT_PICK,
        PHASE_PICK_COMMIT,
        PHASE_POST_DRAFT_SAVE,
        PHASE_RECOMMENDATIONS,
        PHASE_REC_SECTION,
        PHASE_SCORE_AVAILABLE,
        live_draft_perf_action,
        recent_live_draft_actions,
        summarize_live_draft_phases,
    )
    from live_draft_pick_scoring import apply_draft_pick_scoring
    from live_draft_roster_tracker import build_team_roster_tracker, roster_df_for_team
    from live_draft_state import commit_live_draft_room, prepare_live_draft_state
    from live_draft_ui_cache import REC_CACHE_KEY, cached_live_draft_get_available, live_draft_ui_cache_key
    from page_perf_phases import session_perf_phase

    room = _sample_room(pool_size=pool_size)
    team = "Daniel"
    session: dict = {
        "_page_perf_ns": {"page": "Live Draft Room", "timings": {}, "started_at": time.perf_counter()},
        "draft_queue": [],
        "live_draft_state": {},
        "live_draft_room": None,
        "room_your_team": team,
    }
    session["live_draft_room"] = room
    session["live_draft_state"] = {
        "draft_room_id": room["draft_room_id"],
        "status": "in_progress",
        "current_pick_index": 0,
        "draft_board": [],
        "pool_records": room["pool"].to_dict("records"),
        "pool_columns": list(room["pool"].columns),
    }
    st_mock = MagicMock()

    draft_result: dict = {"ok": False, "message": ""}
    patches = [
        patch("page_perf_phases.dev_perf_enabled", return_value=True),
        patch("baseball_persistent_state.force_save_baseball_state", return_value=True),
        patch("draft_room_state.resolve_active_draft_source", return_value="live"),
    ]
    for p in patches:
        p.start()
    try:
        prepare_live_draft_state(session)

        add_player_to_draft_queue(session, "Player 1")
        add_player_to_draft_queue(session, "Player 5")
        remove_player_from_draft_queue(session, "Player 5")

        available_cold = cached_live_draft_get_available(session, room)
        available_warm = cached_live_draft_get_available(session, room)

        cfg = dict(room.get("config") or {})
        roster_df = roster_df_for_team(room, team)

        with live_draft_perf_action(session, "decision_context", phase=PHASE_DECISION_CONTEXT, cache="miss"):
            with session_perf_phase(session, "roster_tracker"):
                tracker = build_team_roster_tracker(room, team)
            with session_perf_phase(session, "category_outlook"):
                compute_category_outlook(
                    roster_df,
                    available_cold,
                    config=cfg,
                    roster_gaps=tracker.get("open_positions"),
                )

        rec_key = live_draft_ui_cache_key(session, room, top_n=8, team=team)
        with live_draft_perf_action(session, "recommendations", phase=PHASE_RECOMMENDATIONS, cache="miss"):
            with session_perf_phase(session, PHASE_SCORE_AVAILABLE):
                scored, _gaps = apply_draft_pick_scoring(
                    available_cold,
                    roster_df,
                    fantasy_format=str(cfg.get("fantasy_format") or "5x5 Roto"),
                    target_counts=_target_counts(cfg),
                    current_pick=1,
                    room=room,
                )
            top_rec = scored.head(8)
        session[REC_CACHE_KEY] = {
            "key": rec_key,
            "top_rec": top_rec,
            "best_avail": scored.head(8),
            "pos_fit": pd.DataFrame(),
            "value_sleep": scored.tail(8),
        }
        with live_draft_perf_action(session, "recommendations", phase=PHASE_RECOMMENDATIONS, cache="hit"):
            entry = session.get(REC_CACHE_KEY)
            _ = entry["top_rec"] if isinstance(entry, dict) else None

        with live_draft_perf_action(session, "rec:Top Picks", phase=PHASE_REC_SECTION):
            _prep_rec_table(top_rec)

        from live_draft_pick_commit import commit_manual_live_pick

        player_row = room["pool"].iloc[0].to_dict()
        with live_draft_perf_action(session, "draft_player", phase=PHASE_DRAFT_PICK):
            with live_draft_perf_action(session, "pick_commit", phase=PHASE_PICK_COMMIT):
                commit = commit_manual_live_pick(
                    session,
                    room,
                    player_row,
                    source="baseline_profile",
                )
            draft_result = {"ok": commit.ok, "message": commit.message}
        with live_draft_perf_action(session, "post_draft_save", phase=PHASE_POST_DRAFT_SAVE):
            from draft_state import remove_player_from_draft_queue

            remove_player_from_draft_queue(session, str(player_row.get("fullName") or ""), reason="drafted")

        with live_draft_perf_action(session, "board_table", phase=PHASE_BOARD_TABLE):
            _build_board_df(session.get("live_draft_room") or room)

        room_after = session.get("live_draft_room") or room
        with live_draft_perf_action(session, "persist:baseline", phase="live_draft_persist"):
            commit_live_draft_room(st_mock, session, room_after, reason="baseline_profile")
    finally:
        for p in patches:
            p.stop()

    timings = dict(session.get("_page_perf_ns", {}).get("timings") or {})
    actions = recent_live_draft_actions(session, limit=32)
    audit = list(session.get("_page_perf_cache_audit") or [])

    return {
        "pool_size": pool_size,
        "draft_ok": bool(draft_result.get("ok")),
        "draft_message": str(draft_result.get("message") or ""),
        "top_phases": summarize_live_draft_phases(session, limit=12),
        "all_top_phases": sorted(timings.items(), key=lambda kv: kv[1], reverse=True)[:12],
        "timings_ms": {k: round(v * 1000.0, 2) for k, v in timings.items()},
        "actions": actions,
        "cache_audit": _cache_summary(audit),
        "action_summary": {
            "queue_add_ms": _action_ms(actions, phase="live_draft_queue_add"),
            "queue_remove_ms": _action_ms(actions, phase="live_draft_queue_remove"),
            "draft_player_ms": _action_ms(actions, phase="live_draft_pick"),
            "pick_commit_ms": _action_ms(actions, phase="live_draft_pick_commit"),
            "post_draft_save_ms": _action_ms(actions, phase="live_draft_post_draft_save"),
            "recommendations_cold_ms": _action_ms(actions, phase="live_draft_recommendations", cache="miss"),
            "recommendations_warm_ms": _action_ms(actions, phase="live_draft_recommendations", cache="hit"),
            "available_pool_cold_ms": _action_ms(actions, phase="live_draft_available_pool", cache="miss"),
            "available_pool_warm_ms": _action_ms(actions, phase="live_draft_available_pool", cache="hit"),
            "decision_context_ms": _action_ms(actions, phase="live_draft_decision_context"),
            "board_table_ms": _action_ms(actions, phase="live_draft_board_table"),
            "rec_section_ms": _action_ms(actions, phase="live_draft_rec_section"),
            "persist_ms": _action_ms(actions, phase="live_draft_persist"),
            "prepare_state_ms": _action_ms(actions, phase="live_draft_prepare_state"),
        },
        "phase_ms": {
            "score_available": _phase_ms(timings, PHASE_SCORE_AVAILABLE),
            "roster_tracker": _phase_ms(timings, "roster_tracker"),
            "category_outlook": _phase_ms(timings, "category_outlook"),
        },
    }


def main() -> int:
    report = _run_baseline(pool_size=40)
    print("=== Live Draft Room — baseline profiling pass ===")
    print(f"Pool size: {report['pool_size']} players")
    print(f"Draft player: {'OK' if report['draft_ok'] else 'FAILED'} — {report.get('draft_message', '')}")

    print("\n--- 1. Slowest Live Draft phases ---")
    for i, (name, sec) in enumerate(report.get("top_phases") or [], start=1):
        print(f"  {i}. {name}: {sec*1000:.1f}ms")

    s = report.get("action_summary") or {}
    print("\n--- 2. Action timings ---")
    rows = [
        ("Add to queue", s.get("queue_add_ms") or []),
        ("Remove from queue", s.get("queue_remove_ms") or []),
        ("Draft player (total)", s.get("draft_player_ms") or []),
        ("  pick commit", s.get("pick_commit_ms") or []),
        ("  post-draft save", s.get("post_draft_save_ms") or []),
        ("Recommendation refresh (cold)", s.get("recommendations_cold_ms") or []),
        ("Recommendation refresh (cached)", s.get("recommendations_warm_ms") or []),
        ("Available pool build (cold)", s.get("available_pool_cold_ms") or []),
        ("Available pool build (cached)", s.get("available_pool_warm_ms") or []),
        ("Decision context build", s.get("decision_context_ms") or []),
        ("Table render prep (board)", s.get("board_table_ms") or []),
        ("Table render prep (rec tab)", s.get("rec_section_ms") or []),
        ("Persist (commit room)", s.get("persist_ms") or []),
        ("Prepare state (all calls)", s.get("prepare_state_ms") or []),
    ]
    for label, vals in rows:
        if not vals:
            print(f"  {label}: n/a")
        elif len(vals) == 1:
            print(f"  {label}: {vals[0]:.1f}ms")
        else:
            print(f"  {label}: {vals[0]:.1f}ms (first), {sum(vals):.1f}ms (total {len(vals)} calls)")

    pm = report.get("phase_ms") or {}
    if pm.get("score_available"):
        print(f"  Scoring sub-phase: {pm['score_available']:.1f}ms")
    if pm.get("roster_tracker") is not None:
        print(f"  Roster tracker sub-phase: {pm['roster_tracker']:.1f}ms")
    if pm.get("category_outlook") is not None:
        print(f"  Category outlook sub-phase: {pm['category_outlook']:.1f}ms")

    print("\n--- 3. Cache hit/miss counts ---")
    audit = report.get("cache_audit") or {}
    if audit:
        for label, counts in audit.items():
            print(f"  {label}: {counts['hit']} hit / {counts['miss']} miss ({counts['total']} total)")
    else:
        print("  (no cache events recorded)")

    print("\n--- 4. Unnecessary recomputes (baseline observations) ---")
    prep_total = sum(s.get("prepare_state_ms") or [])
    prep_calls = len(s.get("prepare_state_ms") or [])
    if prep_calls > 1:
        print(f"  * prepare_live_draft_state ran {prep_calls}x ({prep_total:.1f}ms total) - queue/sync triggers re-hydrate")
    print("  * Queue add/remove call write_canonical_draft_state -> side-effect hydrate on each edit")
    cold_rec = (s.get("recommendations_cold_ms") or [0])[0]
    warm_rec = (s.get("recommendations_warm_ms") or [0])[0]
    if cold_rec > 0 and warm_rec >= 0:
        print(f"  * Recommendation cache: cold {cold_rec:.1f}ms vs warm {warm_rec:.1f}ms - cache busts on pick (expected after draft)")
    print("  * Scoring runs full available pool on cache miss (scales with pool size)")
    print("  * Decision context rebuilds roster_tracker + category_outlook on miss (cheap at pick 1, grows with roster)")

    print("\n--- 5. Recommended first optimization targets ---")
    targets = []
    for name, sec in report.get("top_phases") or []:
        if sec * 1000 > 5:
            targets.append((name, sec * 1000))
    if prep_calls > 1:
        targets.insert(0, ("prepare_live_draft_state (dedupe on queue-only edits)", prep_total))
    targets.extend([
        ("live_draft_score_available (incremental / top-N scoring)", pm.get("score_available") or cold_rec),
        ("live_draft_recommendations cache (don't bust on queue-only session writes)", 0),
        ("live_draft_decision_context (cache per pick revision)", pm.get("roster_tracker") or 0),
    ])
    seen: set[str] = set()
    for i, (name, ms) in enumerate(targets, start=1):
        key = str(name)
        if key in seen:
            continue
        seen.add(key)
        ms_s = f"{ms:.1f}ms" if ms else "verify in UI"
        print(f"  {i}. {name} - {ms_s}")

    out_path = ROOT / "data" / "live_draft_baseline_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nFull report saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
