"""Tests for position-representative AMI available player pool packaging."""

from __future__ import annotations

import unittest

import pandas as pd

from applied_math_context import (
    augment_ami_available_pool_at_send,
    build_baseball_applied_math_context,
    cache_draft_assistant_ami_context,
    extract_player_from_question,
)
from draft_ami_helpers import (
    AMI_POOL_FINAL_CAP,
    build_position_representative_available_pool,
    detect_positions_from_question,
)
from suite_analytical_question import build_submit_context


def _sample_pool_df() -> pd.DataFrame:
    rows = []
    specs = [
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
    for i, (name, pos, ev) in enumerate(specs):
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
    return pd.DataFrame(rows)


class TestPositionRepresentativePool(unittest.TestCase):
    def test_top12_ev_zero_catchers_but_pool_includes_catchers(self) -> None:
        df = _sample_pool_df()
        rows, diag, _lookup = build_position_representative_available_pool(
            df,
            needed_positions=["C", "SS"],
            drafted_players=["Aaron Judge"],
        )
        top12 = df.sort_values("Expected Fantasy Value", ascending=False).head(12)
        catchers_in_top12 = sum(1 for _, r in top12.iterrows() if r["Primary Position"] == "C")
        self.assertEqual(catchers_in_top12, 0)
        self.assertGreaterEqual(diag["catchers_in_available_players"], 1)
        self.assertIn("C", diag["available_players_position_counts"])
        catcher_names = {r["player"] for r in rows if r.get("Primary Position") == "C"}
        self.assertTrue(catcher_names & {"Cal Raleigh", "William Contreras", "Adley Rutschman"})

    def test_detect_catcher_from_question(self) -> None:
        self.assertIn("C", detect_positions_from_question("Who is the next catcher drafted?"))

    def test_detect_shortstop_wait_question(self) -> None:
        self.assertIn("SS", detect_positions_from_question("Can I wait on shortstop this round?"))

    def test_detect_position_run_question(self) -> None:
        positions = detect_positions_from_question("When does the OF position run start?")
        self.assertIn("OF", positions)

    def test_jose_outside_top12_included_via_third_base_slice(self) -> None:
        df = _sample_pool_df()
        rows, _diag, lookup = build_position_representative_available_pool(df, needed_positions=["C"])
        names = {r["player"] for r in rows}
        self.assertIn("Jose Ramirez", names)
        self.assertIn("jose ramirez", lookup)

    def test_jose_question_player_row_bound_after_send(self) -> None:
        df = _sample_pool_df().sort_values("Expected Fantasy Value", ascending=False)
        session: dict = {"room_your_team": "Daniel", "room_team_count": 12}
        cache_draft_assistant_ami_context(
            session,
            page="Draft Assistant Simulator",
            recs_df=df.head(2),
            current_pick=6,
            my_roster=["Juan Soto"],
            drafted_total=5,
            draft_format="5x5 Roto",
            assistant_team="Daniel",
            needed_positions=["3B"],
            category_needs=["HR"],
            drafted_players=["Aaron Judge"],
            best_available_df=df.head(6),
            available_df=df,
        )
        ctx = build_submit_context(
            "baseball",
            "Draft Assistant Simulator",
            session,
            context_extra_builder=lambda: build_baseball_applied_math_context(
                "Draft Assistant Simulator", session
            ),
            question="Why Jose Ramirez?",
        )
        names = {r["player"] for r in ctx.get("available_players") or []}
        self.assertIn("Jose Ramirez", names)
        self.assertEqual(extract_player_from_question("Why Jose Ramirez?"), "Jose Ramirez")
        self.assertIsNotNone(ctx.get("question_player_row"))

    def test_send_path_includes_catchers_for_next_catcher_question(self) -> None:
        df = _sample_pool_df()
        session: dict = {"room_your_team": "Daniel", "room_team_count": 12}
        cache_draft_assistant_ami_context(
            session,
            page="Draft Assistant Simulator",
            recs_df=df.head(2),
            current_pick=6,
            my_roster=["Juan Soto", "Elly De La Cruz"],
            drafted_total=5,
            draft_format="5x5 Roto",
            assistant_team="Daniel",
            needed_positions=["C", "SS"],
            category_needs=["HR", "SB"],
            drafted_players=["Aaron Judge"],
            best_available_df=df.sort_values("Expected Fantasy Value", ascending=False).head(6),
            available_df=df.sort_values("Expected Fantasy Value", ascending=False),
        )
        ctx = build_submit_context(
            "baseball",
            "Draft Assistant Simulator",
            session,
            context_extra_builder=lambda: build_baseball_applied_math_context(
                "Draft Assistant Simulator", session
            ),
            question="Who is the most likely catcher to be drafted next?",
        )
        avail = ctx.get("available_players") or []
        diag = ctx.get("player_pool_diagnostics") or {}
        self.assertGreaterEqual(diag.get("catchers_in_available_players", 0), 1)
        self.assertGreaterEqual(len(avail), 12)
        self.assertLessEqual(len(avail), AMI_POOL_FINAL_CAP)
        catcher_rows = [r for r in avail if str(r.get("Primary Position", "")).upper() == "C"]
        self.assertGreaterEqual(len(catcher_rows), 1)

    def test_roster_weakness_context_has_position_counts(self) -> None:
        df = _sample_pool_df()
        session: dict = {"room_your_team": "Daniel", "room_team_count": 12}
        cache_draft_assistant_ami_context(
            session,
            page="Draft Assistant Simulator",
            recs_df=df.head(3),
            current_pick=6,
            my_roster=["Juan Soto", "Elly De La Cruz"],
            drafted_total=5,
            draft_format="5x5 Roto",
            assistant_team="Daniel",
            needed_positions=["C", "SS"],
            category_needs=["HR", "SB"],
            drafted_players=["Aaron Judge"],
            best_available_df=df.head(6),
            available_df=df,
        )
        ctx = build_submit_context(
            "baseball",
            "Draft Assistant Simulator",
            session,
            context_extra_builder=lambda: build_baseball_applied_math_context(
                "Draft Assistant Simulator", session
            ),
            question="What is my biggest roster weakness?",
        )
        diag = ctx.get("player_pool_diagnostics") or {}
        self.assertEqual(diag.get("needed_positions"), ["C", "SS"])
        self.assertGreaterEqual(diag.get("available_players_count", 0), 12)
        self.assertIn("player_pool_source", diag)

    def test_augment_adds_requested_position_rows(self) -> None:
        df = _sample_pool_df()
        _rows, _diag, lookup = build_position_representative_available_pool(df, needed_positions=[])
        ctx: dict = {"available_players": [], "draft_snapshot": {}}
        augment_ami_available_pool_at_send(
            ctx,
            "Who is the next catcher likely to be drafted?",
            {"_ami_undrafted_pool_lookup": lookup},
        )
        catchers = [r for r in ctx["available_players"] if r.get("Primary Position") == "C"]
        self.assertGreaterEqual(len(catchers), 1)


if __name__ == "__main__":
    unittest.main()
