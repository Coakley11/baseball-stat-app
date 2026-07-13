"""Tests for live_draft_ux presentation helpers."""

from __future__ import annotations

import unittest

import pandas as pd

from live_draft_ux import (
    apply_survival_display_columns,
    confidence_label_from_score,
    describe_strength,
    describe_strengths,
    format_of_slot_eligibility,
    format_participant_identity,
    format_scarcity_explanation,
    format_survival_probability,
    format_your_fantasy_team,
    resolve_next_pick_for_survival,
    sort_recommendation_table,
    star_rating,
    user_facing_start_step,
)


class LiveDraftUxTests(unittest.TestCase):
    def test_participant_identity_canonical(self) -> None:
        text = format_participant_identity("Donny", role="Commissioner", team="Team A")
        self.assertEqual(text, "Donny (Commissioner) — Team A")

    def test_your_fantasy_team_copy(self) -> None:
        self.assertIn("Team B", format_your_fantasy_team("Team B"))

    def test_strength_descriptions(self) -> None:
        self.assertEqual(describe_strength("HR"), "Elite Power")
        self.assertEqual(describe_strengths(["HR", "RBI"]), ["Elite Power", "Excellent Run Production"])

    def test_of_slot_eligibility_plural(self) -> None:
        self.assertIn("3 remaining", format_of_slot_eligibility(3))

    def test_scarcity_explanation(self) -> None:
        text = format_scarcity_explanation("OF", tier1_remaining=5, picks_until_dropoff=3)
        self.assertIn("Only 5 Tier-1 OF remain", text)
        self.assertIn("next 3 picks", text)

    def test_survival_formatting(self) -> None:
        self.assertEqual(format_survival_probability(0.72), "72%")
        self.assertEqual(format_survival_probability(None), "—")

    def test_survival_display_columns(self) -> None:
        df = pd.DataFrame({"Survival Probability": [0.95, 0.38]})
        out = apply_survival_display_columns(df)
        self.assertEqual(out.iloc[0]["Survival Probability"], "95%")
        self.assertEqual(out.iloc[1]["Survival Probability"], "38%")

    def test_resolve_next_pick_from_room(self) -> None:
        room = {
            "current_pick_index": 0,
            "pick_order": [
                {"Pick": 1, "Team": "Team A"},
                {"Pick": 2, "Team": "Team B"},
                {"Pick": 3, "Team": "Team A"},
            ],
        }
        nxt = resolve_next_pick_for_survival(
            current_pick=1,
            next_user_pick=None,
            num_teams=2,
            room=room,
            user_team="Team A",
        )
        self.assertEqual(nxt, 3)

    def test_sort_recommendation_table(self) -> None:
        df = pd.DataFrame(
            {
                "Player": ["A", "B", "C"],
                "Decision Score": [50, 90, 70],
            }
        )
        out = sort_recommendation_table(df, "Decision Score")
        self.assertEqual(out.iloc[0]["Player"], "B")

    def test_confidence_label(self) -> None:
        label, stars = confidence_label_from_score(0.88)
        self.assertIn("High", label)
        self.assertIn("★", stars)

    def test_user_facing_start_step(self) -> None:
        self.assertEqual(user_facing_start_step("start_clicked"), "Preparing Draft…")
        self.assertEqual(user_facing_start_step("first_render_ready"), "Draft Live")
        self.assertNotIn("start_clicked", user_facing_start_step("start_clicked"))

    def test_star_rating(self) -> None:
        self.assertTrue(star_rating(5, label="Home Runs").startswith("★★★★★"))


if __name__ == "__main__":
    unittest.main()
