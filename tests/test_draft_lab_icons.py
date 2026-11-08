"""Draft Lab's result tabs and answer buttons carry the app's colourful icons (owner review, 2026-11-08).

Icons are display-only: the stored tab value stays the plain name, so saved results and the
"Continue Draft Analysis" handoff (draft_lab_preferred_tab = "Team Analysis") still match.
"""

import unittest
from pathlib import Path

import action_icons as icons
from draft_lab_state import DRAFT_LAB_RESULT_TABS, draft_lab_tab_label

APP = (Path(__file__).resolve().parents[1] / "streamlit_app.py").read_text(encoding="utf-8")


class DraftLabIconTests(unittest.TestCase):
    def test_every_result_tab_has_a_distinct_colourful_icon(self):
        labels = [draft_lab_tab_label(t) for t in DRAFT_LAB_RESULT_TABS]
        self.assertEqual(labels, [f"{icons.BOARD} Draft Board", f"{icons.ROSTER} Team Rosters",
                                  f"{icons.ANALYZE} Team Analysis", f"{icons.REVIEW} Best / Questionable Picks",
                                  f"{icons.EXPORT} Exports"])
        self.assertEqual(len({lab.split(" ", 1)[0] for lab in labels}), len(labels))
        for lab in labels:
            self.assertNotIn(":material/", lab)  # emoji, never monochrome Material Symbols

    def test_icons_are_display_only(self):
        self.assertIn("format_func=draft_lab_tab_label", APP)
        self.assertEqual(draft_lab_tab_label("Unknown"), "Unknown")
        self.assertIn('"Team Analysis"', APP)  # the plain value is still what is stored and compared

    def test_answer_buttons_use_the_same_icons(self):
        self.assertIn('draft_lab_tab_label("Team Analysis")', APP)
        self.assertIn('draft_lab_tab_label("Best / Questionable Picks")', APP)


if __name__ == "__main__":
    unittest.main()
