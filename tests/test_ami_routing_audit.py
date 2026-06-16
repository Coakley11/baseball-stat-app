"""AMI Routing / Interpretation Audit — regression tests for the four failing cases."""
from __future__ import annotations

import unittest

from applied_math_context import (
    extract_age_constraint_from_question,
    extract_comparison_players_from_question,
    extract_season_constraint_from_question,
)
from baseball_ami_pages import (
    detect_comparison_send_intent,
    detect_trend_send_intent,
    finalize_comparison_context_for_send,
    finalize_sleepers_context_for_send,
    finalize_trend_context_for_send,
)
from draft_ami_helpers import extract_draft_team_from_question, is_roster_weakness_question


# ---------------------------------------------------------------------------
# CASE 1 — Trend Value: two-player comparison question
# ---------------------------------------------------------------------------
class TestTrendTwoPlayerComparison(unittest.TestCase):
    def test_extract_better_pick_than(self) -> None:
        """'Is A a better pick than B' must yield two players."""
        q = "Is Kameron Misner a better pick than Stone Garrett even though he has a lower trend in OPS?"
        a, b = extract_comparison_players_from_question(q)
        self.assertEqual(a, "Kameron Misner", f"player_a wrong: got {a!r}")
        self.assertEqual(b, "Stone Garrett", f"player_b wrong: got {b!r}")

    def test_detect_trend_comparison_intent(self) -> None:
        q = "Is Kameron Misner a better pick than Stone Garrett even though he has a lower trend in OPS?"
        intent = detect_trend_send_intent(q)
        self.assertEqual(intent, "trend_player_comparison")

    def test_finalize_trend_sets_routing_hint_and_keeps_players(self) -> None:
        """finalize_trend_context_for_send must set routing_hint and preserve player_a/b."""
        ctx: dict = {
            "player_a": "Kameron Misner",
            "player_b": "Stone Garrett",
        }
        session: dict = {}
        q = "Is Kameron Misner a better pick than Stone Garrett even though he has a lower trend in OPS?"
        finalize_trend_context_for_send(ctx, session, question=q)
        self.assertEqual(ctx.get("routing_hint"), "trend_player_comparison")
        self.assertEqual(ctx.get("player_a"), "Kameron Misner")
        self.assertEqual(ctx.get("player_b"), "Stone Garrett")

    def test_pure_trend_question_clears_players(self) -> None:
        """A single-player trend question must clear stale player_a/b."""
        ctx: dict = {"player_a": "old", "player_b": "old"}
        session: dict = {}
        finalize_trend_context_for_send(ctx, session, question="Is Jose Ramirez's OPS trend sustainable?")
        self.assertFalse(ctx.get("player_a"))
        self.assertFalse(ctx.get("player_b"))
        self.assertEqual(ctx.get("routing_hint"), "trend_significance")


# ---------------------------------------------------------------------------
# CASE 2 — Comparison Tool: age constraint + historical intent
# ---------------------------------------------------------------------------
class TestComparisonHistoricalConstraints(unittest.TestCase):
    def test_extract_better_player_than(self) -> None:
        q = "Was Soto a better player than Ken Griffey Jr. between the ages of 22-30?"
        a, b = extract_comparison_players_from_question(q)
        self.assertEqual(a, "Soto", f"player_a wrong: got {a!r}")
        self.assertIn("Griffey", b, f"player_b should contain Griffey, got {b!r}")

    def test_extract_age_range(self) -> None:
        q = "Was Soto a better player than Ken Griffey Jr. between the ages of 22-30?"
        age = extract_age_constraint_from_question(q)
        self.assertEqual(age, "22-30")

    def test_extract_age_range_variant(self) -> None:
        self.assertEqual(extract_age_constraint_from_question("Compare them at ages 25 to 32"), "25-32")
        self.assertEqual(extract_age_constraint_from_question("from age 20 to 28 seasons"), "20-28")

    def test_detect_historical_age_intent(self) -> None:
        q = "Was Soto a better player than Ken Griffey Jr. between the ages of 22-30?"
        intent = detect_comparison_send_intent(q)
        self.assertEqual(intent, "comparison_historical_age")

    def test_finalize_comparison_adds_age_constraint(self) -> None:
        q = "Was Soto a better player than Ken Griffey Jr. between the ages of 22-30?"
        ctx: dict = {}
        session: dict = {}
        finalize_comparison_context_for_send(ctx, session, question=q)
        self.assertEqual(ctx.get("comparison_age_range"), "22-30")
        self.assertIn("22-30", ctx.get("comparison_constraint_note", ""))
        self.assertEqual(ctx.get("routing_hint"), "comparison_historical_age")

    def test_extract_season_range(self) -> None:
        q = "Compare their stats from 2015 to 2022"
        season = extract_season_constraint_from_question(q)
        self.assertEqual(season, "2015-2022")

    def test_detect_historical_season_intent(self) -> None:
        q = "Was Bonds better than Griffey from 1995 to 2004?"
        intent = detect_comparison_send_intent(q)
        self.assertEqual(intent, "comparison_historical_season")


# ---------------------------------------------------------------------------
# CASE 3 — Sleepers: two-player comparison with sleeper keyword
# ---------------------------------------------------------------------------
class TestSleepersTwoPlayerComparison(unittest.TestCase):
    def test_extract_better_than_really(self) -> None:
        q = "Is Isaac Collins really better than Nathan Lukes since he is a curve adjusted sleeper?"
        a, b = extract_comparison_players_from_question(q)
        self.assertTrue(a, f"player_a should be extracted, got {a!r}")
        self.assertTrue(b, f"player_b should be extracted, got {b!r}")

    def test_finalize_sleepers_sets_comparison_routing(self) -> None:
        """On sleepers page with two players + 'sleeper' keyword → sleeper_comparison routing."""
        q = "Is Isaac Collins really better than Nathan Lukes since he is a curve adjusted sleeper?"
        ctx: dict = {
            "source_page": "Fantasy Sleepers & Busts",
            "player_a": "Isaac Collins",
            "player_b": "Nathan Lukes",
        }
        session: dict = {}
        finalize_sleepers_context_for_send(ctx, session, question=q)
        self.assertEqual(ctx.get("routing_hint"), "sleeper_comparison")
        self.assertEqual(ctx.get("intent"), "sleeper_comparison_analysis")
        # Both players must be preserved
        self.assertEqual(ctx.get("player_a"), "Isaac Collins")
        self.assertEqual(ctx.get("player_b"), "Nathan Lukes")


# ---------------------------------------------------------------------------
# CASE 4 — Draft: roster weakness detection and routing
# ---------------------------------------------------------------------------
class TestDraftRosterWeaknessRouting(unittest.TestCase):
    def test_is_roster_weakness_question(self) -> None:
        self.assertTrue(is_roster_weakness_question(
            "What is Daniel's biggest statistical and position weakness in this draft?"
        ))
        self.assertTrue(is_roster_weakness_question("Where am I weak in this draft?"))
        self.assertTrue(is_roster_weakness_question("What's my roster gap at catcher?"))
        self.assertFalse(is_roster_weakness_question("Who should I draft next?"))
        self.assertFalse(is_roster_weakness_question("Is Trout a good pick at 5?"))

    def test_extract_team_from_possessive_weakness(self) -> None:
        q = "What is Daniel's biggest statistical and position weakness in this draft?"
        team = extract_draft_team_from_question(q, my_team="Daniel", team_names=["Daniel", "Team 2"])
        self.assertEqual(team, "Daniel")

    def test_extract_team_possessive_no_known_names(self) -> None:
        """When no team_names provided, possessive owner should still be extracted."""
        q = "What is Daniel's biggest weakness in this draft?"
        team = extract_draft_team_from_question(q)
        self.assertIn("Daniel", team, f"Expected 'Daniel' in result, got {team!r}")


if __name__ == "__main__":
    unittest.main()
