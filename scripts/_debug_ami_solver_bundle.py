"""Trace Baseball send context -> AMI _draft_context_bundle -> solve_baseball_draft."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
AMI = Path(__file__).resolve().parents[2] / "applied-mathematical-intelligence"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(AMI))

from applied_math_context import build_baseball_applied_math_context, cache_draft_assistant_ami_context
from components.applied_math_solvers import (
    _draft_context_bundle,
    _draft_question_mode,
    _resolve_focus_player,
    solve_baseball_draft,
)

QUESTION = "Who is the best player available?"


def _build_send_context() -> dict:
    rows = [
        {"fullName": "Kyle Tucker", "Primary Position": "OF", "Expected Fantasy Value": 0.91, "Market Rank": 8, "Model Rank": 8, "Fantasy Edge": 0},
        {"fullName": "William Contreras", "Primary Position": "C", "Expected Fantasy Value": 0.80, "Market Rank": 14, "Model Rank": 14, "Fantasy Edge": 0},
    ]
    available = pd.DataFrame(rows)
    session: dict = {
        "room_your_team": "Daniel",
        "room_team_count": 2,
        "live_draft_room": {"current_pick_index": 0, "config": {"num_teams": 12}},
    }
    cache_draft_assistant_ami_context(
        session,
        page="Draft Assistant Simulator",
        recs_df=available.head(1),
        current_pick=8,
        my_roster=["Aaron Judge", "Cal Raleigh"],
        drafted_total=7,
        draft_format="5x5 Roto",
        assistant_team="Daniel",
        needed_positions=["C", "OF"],
        category_needs=["HR"],
        drafted_players=["Aaron Judge"],
        best_available_df=available.head(1),
        available_df=available,
    )
    base = {"workflow": "Fantasy draft", "current_pick": 1}
    extra = build_baseball_applied_math_context("Draft Assistant Simulator", session)
    merged = dict(base)
    for k, v in extra.items():
        if v is None or v == "":
            continue
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            block = dict(merged[k])
            block.update(v)
            merged[k] = block
        else:
            merged[k] = v
    return merged


def _sparse_url_context() -> dict:
    return {
        "source_app": "Baseball",
        "page": "Draft Assistant Simulator",
        "workflow": "Fantasy draft",
        "current_pick": 1,
        "draft_round": 1,
    }


def _report(label: str, ctx: dict) -> None:
    snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
    diag = ctx.get("player_pool_diagnostics") if isinstance(ctx.get("player_pool_diagnostics"), dict) else {}
    top = ctx.get("available_players") or []
    snap_rows = snap.get("available_players") or []
    bundle = _draft_context_bundle(ctx)
    mode = _draft_question_mode(QUESTION)
    player = _resolve_focus_player(QUESTION, ctx, bundle)
    result = solve_baseball_draft(ctx, QUESTION)
    print(f"\n=== {label} ===")
    print(f"  ctx.available_players count: {len(top)}")
    print(f"  draft_snapshot.available_players count: {len(snap_rows)}")
    print(f"  player_pool_source: {diag.get('player_pool_source')}")
    print(f"  bundle.available count: {len(bundle.get('available') or [])}")
    print(f"  bundle.pick: {bundle.get('pick')} mode: {mode} focus_player: {player!r}")
    print(f"  answer: {(result.short_answer or '')[:180]}")
    if "0 available names" in (result.short_answer or "") or "0 available names" in str(result.computed):
        print("  ** contains 0 available names **")


def main() -> None:
    _report("Full Baseball send context", _build_send_context())
    _report("Sparse URL-only context (hydration failure sim)", _sparse_url_context())


if __name__ == "__main__":
    main()
