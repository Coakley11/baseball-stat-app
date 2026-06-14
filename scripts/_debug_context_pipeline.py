"""Trace Baseball → AMI context for Draft Assistant available-player pool."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from applied_math_context import build_baseball_applied_math_context, cache_draft_assistant_ami_context
from suite_analytical_question import build_submit_context


def _pos_counts(rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        pos = str(r.get("Primary Position") or r.get("position") or r.get("pos") or "?")
        out[pos] = out.get(pos, 0) + 1
    return out


def _report(label: str, ctx: dict) -> None:
    snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
    avail = ctx.get("available_players") or snap.get("available_players") or []
    recs = ctx.get("recommended_players") or snap.get("recommended_players") or []
    diag = ctx.get("player_pool_diagnostics") or snap.get("player_pool_diagnostics") or {}
    print(f"\n=== {label} ===")
    print(f"  draft_snapshot present: {bool(snap)}")
    print(f"  ctx.available_players rows: {len(avail)}")
    print(f"  snap.available_players rows: {len(snap.get('available_players') or [])}")
    print(f"  recommended_players rows: {len(recs)}")
    print(f"  positions in available: {_pos_counts(avail)}")
    print(f"  catchers in available: {sum(1 for r in avail if str(r.get('Primary Position','')).upper()=='C')}")
    print(f"  needed_positions: {ctx.get('needed_positions') or snap.get('needed_positions')}")
    print(f"  category_needs: {ctx.get('category_needs') or snap.get('category_needs')}")
    print(f"  player_pool_diagnostics: {diag}")


def scenario_no_catchers_in_top12() -> None:
    """Simulates deployed failure: top-12 EV slice has no catchers."""
    rows = []
    for i, (name, pos, ev) in enumerate(
        [
            ("Aaron Judge", "OF", 0.95),
            ("Juan Soto", "OF", 0.94),
            ("Kyle Tucker", "OF", 0.91),
            ("Freddie Freeman", "1B", 0.90),
            ("Matt Olson", "1B", 0.89),
            ("Jose Ramirez", "3B", 0.88),
            ("Vladimir Guerrero Jr.", "1B", 0.87),
            ("Kyle Schwarber", "OF", 0.86),
            ("Bobby Witt Jr.", "SS", 0.85),
            ("Elly De La Cruz", "SS", 0.84),
            ("Corbin Carroll", "OF", 0.83),
            ("Mookie Betts", "OF", 0.82),
            ("Cal Raleigh", "C", 0.81),
            ("William Contreras", "C", 0.80),
            ("Adley Rutschman", "C", 0.79),
        ]
    ):
        rows.append(
            {
                "fullName": name,
                "Primary Position": pos,
                "Expected Fantasy Value": ev,
                "Market Rank": i + 1,
                "Model Rank": i + 1,
                "Fantasy Edge": 0,
            }
        )
    available = pd.DataFrame(rows)
    recs = available.head(2)
    session: dict = {
        "room_your_team": "Daniel",
        "room_team_count": 12,
        "draft_queue": ["Cal Raleigh"],
        "draft_assistant_focus_players": ["Bobby Witt Jr."],
    }
    cache_draft_assistant_ami_context(
        session,
        page="Draft Assistant Simulator",
        recs_df=recs,
        current_pick=6,
        my_roster=["Juan Soto", "Elly De La Cruz"],
        drafted_total=5,
        draft_format="5x5 Roto",
        assistant_team="Daniel",
        needed_positions=["C", "SS"],
        category_needs=["HR", "SB"],
        drafted_players=["Aaron Judge", "Juan Soto"],
        best_available_df=available.sort_values("Expected Fantasy Value", ascending=False).head(6),
        available_df=available.sort_values("Expected Fantasy Value", ascending=False),
        position_scarcity=2.4,
    )
    ctx = build_submit_context(
        "baseball",
        "Draft Assistant Simulator",
        session,
        context_extra_builder=lambda: build_baseball_applied_math_context("Draft Assistant Simulator", session),
        question="Who is the most likely catcher to be drafted next?",
    )
    _report("Position-representative pool (send path)", ctx)


def scenario_no_cache() -> None:
    """Simulates send without Draft Assistant cache populated."""
    session: dict = {
        "draft_queue": ["Cal Raleigh"],
        "room_your_team": "Daniel",
    }
    ctx = build_baseball_applied_math_context("Draft Assistant Simulator", session)
    _report("No _ami_draft_snapshot cache", ctx)


def main() -> None:
    print("Baseball -> AMI context pipeline diagnostic")
    scenario_no_catchers_in_top12()
    scenario_no_cache()
    print("\nDone.")


if __name__ == "__main__":
    main()
