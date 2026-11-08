"""Recommendation card scores are explained (owner review, 2026-11-08). Calculations are unchanged.

Each card metric has hover text saying what it measures and how to read its number, and a collapsed "What do
these scores mean?" panel covers phones, which have no hover.
"""

import re
import unittest
from pathlib import Path

import pandas as pd

from draft_score_display import SCORE_SCALES, score_explanation
from player_photos import build_draft_score_metrics_html as draft_metrics_html

ROOT = Path(__file__).resolve().parents[1]
CARD_METRICS = ("Decision Score", "Player Grade", "Roster Fit Score", "Positional Scarcity")


class ScoreExplanationTests(unittest.TestCase):
    def test_every_card_metric_has_a_meaning_and_a_scale(self) -> None:
        for label in CARD_METRICS:
            text = score_explanation(label)
            self.assertTrue(text, label)
            self.assertIn(SCORE_SCALES[label], text)
            self.assertIsNone(re.search(r"\b(he|him|his)\b", text), label)  # names/"the player", not pronouns

    def test_card_metrics_carry_hover_text(self) -> None:
        row = pd.Series({"Decision Score": 0.91, "Expected Fantasy Value": 0.88, "Draft Fit Score": 0.6,
                         "Position Scarcity Score": 0.4, "Market Rank": 12, "Model Rank": 8})
        out = draft_metrics_html(row, show_decision_score=True, show_scarcity=True)
        for label in ("Decision Score", "Player Grade", "Roster Fit Score"):
            self.assertRegex(out, rf'<div class="bb-fact" title="[^"]+"><span class="bb-fact-l">{label}</span>')

    def test_phones_get_the_explanations_too(self) -> None:
        src = (ROOT / "live_draft_room_ui.py").read_text(encoding="utf-8")
        self.assertIn('st.expander("What do these scores mean?", expanded=False)', src)


if __name__ == "__main__":
    unittest.main()
