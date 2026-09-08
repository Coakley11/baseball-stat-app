"""Solo recommendation UI must paint full player cards, not a queue strip."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]


class SoloRecommendationCardUxTests(unittest.TestCase):
    def test_solo_early_viewport_source_uses_full_cards_not_dense_strip(self) -> None:
        src = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        # Locate the Solo early-viewport recommendations block.
        marker = "Solo first-viewport landing: full player recommendation cards"
        self.assertIn(marker, src)
        block = src.split(marker, 1)[1].split("ldr_section(st.session_state, \"room_controls_timer\"", 1)[0]
        self.assertIn('st.markdown("##### Recommendations")', block)
        self.assertNotIn('st.markdown("### Recommended picks")', block)
        self.assertIn("dense=False", block)
        self.assertIn('layout="horizontal"', block)
        self.assertNotIn("dense=True", block)
        self.assertIn("max_cards_override=3", block)

    def test_rec_card_renderer_has_no_queue_only_dense_strip(self) -> None:
        src = (_REPO / "live_draft_room_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("ld-rec-dense-card", src)
        self.assertIn("ld-rec-card-header", src)
        self.assertIn("Why Recommended", src)
        self.assertIn("Draft Player", src)

    def test_render_live_draft_rec_cards_emits_full_card_header(self) -> None:
        from live_draft_room_ui import render_live_draft_rec_cards

        rec = pd.DataFrame(
            [
                {
                    "fullName": "Manny Machado",
                    "playerID": "m1",
                    "Primary Position": "3B",
                    "Team": "SD",
                    "Fantasy Edge": 2.0,
                    "Decision Score": 0.8,
                    "Positional Fit": 0.7,
                    "Expected Fantasy Value": 90.0,
                    "Survival Probability": 0.4,
                    "Draft Fit Score": 0.75,
                },
                {
                    "fullName": "Ketel Marte",
                    "playerID": "m2",
                    "Primary Position": "2B",
                    "Team": "AZ",
                    "Fantasy Edge": 1.0,
                    "Decision Score": 0.7,
                    "Positional Fit": 0.6,
                    "Expected Fantasy Value": 85.0,
                    "Survival Probability": 0.5,
                    "Draft Fit Score": 0.7,
                },
                {
                    "fullName": "Jazz Chisholm Jr.",
                    "playerID": "m3",
                    "Primary Position": "2B",
                    "Team": "NYY",
                    "Fantasy Edge": 0.5,
                    "Decision Score": 0.65,
                    "Positional Fit": 0.55,
                    "Expected Fantasy Value": 80.0,
                    "Survival Probability": 0.55,
                    "Draft Fit Score": 0.65,
                },
            ]
        )
        room = {
            "draft_room_id": "SOLOTEST",
            "current_pick_index": 0,
            "status": "in_progress",
            "config": {"your_team": "Team A", "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1}},
            "pool": rec.copy(),
            "teams": ["Team A", "Team B"],
            "rosters": {"Team A": [], "Team B": []},
        }
        session: dict = {"draft_queue": []}
        st = MagicMock()
        # Support `with st.container(...)` / `with st.columns(...)` / expander.
        container = MagicMock()
        container.__enter__ = MagicMock(return_value=container)
        container.__exit__ = MagicMock(return_value=False)
        st.container.return_value = container
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        st.columns.return_value = [col, col, col]
        expander = MagicMock()
        expander.__enter__ = MagicMock(return_value=expander)
        expander.__exit__ = MagicMock(return_value=False)
        st.expander.return_value = expander

        with patch("live_draft_room_ui.record_rec_card_diagnostics"):
            render_live_draft_rec_cards(
                st,
                session,
                room,
                rec,
                max_cards=3,
                layout="horizontal",
                dense=False,
            )

        markdown_blobs = "\n".join(
            str(c.args[0]) for c in st.markdown.call_args_list if c.args
        )
        self.assertIn("ld-rec-card-header", markdown_blobs)
        self.assertNotIn("ld-rec-dense-card", markdown_blobs)
        self.assertIn("Manny Machado", markdown_blobs)
        button_labels = [
            str(c.kwargs.get("key") or "")
            for c in st.button.call_args_list
        ]
        # Draft + Queue actions belong on the full card.
        self.assertTrue(any("rec_card_draft_" in k for k in button_labels) or any(
            (c.args and "Draft" in str(c.args[0])) for c in st.button.call_args_list
        ))


if __name__ == "__main__":
    unittest.main()
