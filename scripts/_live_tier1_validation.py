"""Local send-path validation mirroring user's live draft board (Pick 8)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from applied_math_context import build_baseball_applied_math_context, cache_draft_assistant_ami_context
from suite_analytical_question import build_submit_context

DRAFTED = [
    "Aaron Judge",
    "Francisco Lindor",
    "Juan Soto",
    "Cal Raleigh",
    "Anthony Volpe",
    "Pete Alonso",
    "Julio Rodriguez",
]
SPECS = [
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
    ("William Contreras", "C", 0.80),
    ("Adley Rutschman", "C", 0.79),
    ("Salvador Perez", "C", 0.78),
    ("Junior Caminero", "3B", 0.77),
    ("Rafael Devers", "3B", 0.76),
]
QUESTIONS = {
    "Q1": "Who is the best player available?",
    "Q2": "Should I draft a catcher or outfielder next?",
    "Q3": "Why Jose Ramirez?",
    "Q4": "Who is the next catcher likely to be drafted?",
}


def main() -> None:
    rows = [
        {
            "fullName": name,
            "Primary Position": pos,
            "Expected Fantasy Value": ev,
            "Market Rank": i + 8,
            "Model Rank": i + 8,
            "Fantasy Edge": 0,
        }
        for i, (name, pos, ev) in enumerate(SPECS)
    ]
    available = pd.DataFrame(rows).sort_values("Expected Fantasy Value", ascending=False)
    session: dict = {"room_your_team": "Daniel", "room_team_count": 2, "draft_queue": []}
    cache_draft_assistant_ami_context(
        session,
        page="Draft Assistant Simulator",
        recs_df=available.head(3),
        current_pick=8,
        my_roster=["Aaron Judge", "Cal Raleigh", "Anthony Volpe"],
        drafted_total=7,
        draft_format="5x5 Roto",
        assistant_team="Daniel",
        needed_positions=["C", "OF", "SS"],
        category_needs=["HR", "RBI"],
        drafted_players=DRAFTED,
        best_available_df=available.head(6),
        available_df=available,
    )
    diag0 = session.get("_ami_draft_projection", {}).get("player_pool_diagnostics", {})
    print("=== LOCAL SEND-PATH (user board Pick 8, Cal Raleigh drafted) ===")
    print("CACHE DIAG:", json.dumps(diag0, default=str))
    for qid, question in QUESTIONS.items():
        ctx = build_submit_context(
            "baseball",
            "Draft Assistant Simulator",
            session,
            context_extra_builder=lambda: build_baseball_applied_math_context(
                "Draft Assistant Simulator", session
            ),
            question=question,
        )
        avail = ctx.get("available_players") or []
        diag = ctx.get("player_pool_diagnostics") or {}
        catchers = [r["player"] for r in avail if str(r.get("Primary Position", "")).upper() == "C"]
        ofs = [r["player"] for r in avail if str(r.get("Primary Position", "")).upper() == "OF"]
        print(f"--- {qid}: {question}")
        print(
            f"  count={len(avail)} catchers={len(catchers)} OF={len(ofs)} "
            f"source={diag.get('player_pool_source')}"
        )
        print(f"  catchers: {catchers}")
        print(f"  OF sample: {ofs[:4]}")
        print(f"  top3: {[r['player'] for r in avail[:3]]}")
        print(f"  requested_position: {diag.get('requested_position')}")
        print(
            f"  question_player_row: {bool(ctx.get('question_player_row'))} "
            f"player={ctx.get('question_player')}"
        )


if __name__ == "__main__":
    main()
