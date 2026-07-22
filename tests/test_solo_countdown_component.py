"""Packaging tests for the Solo countdown wake Streamlit component."""

from __future__ import annotations

import unittest
from pathlib import Path


class SoloCountdownComponentPackagingTests(unittest.TestCase):
    def test_frontend_index_exists(self) -> None:
        index = (
            Path(__file__).resolve().parents[1]
            / "solo_countdown_component"
            / "frontend"
            / "index.html"
        )
        self.assertTrue(index.is_file())
        content = index.read_text(encoding="utf-8")
        self.assertIn("streamlit:componentReady", content)
        self.assertIn('apiVersion: 1', content)
        self.assertIn("streamlit:render", content)
        self.assertIn("streamlit:setComponentValue", content)
        self.assertIn("solo-expire-client", content)
        self.assertIn("component_value_sent", content)
        self.assertIn("browser_deadline_crossed", content)
        self.assertNotIn("location.assign", content)


if __name__ == "__main__":
    unittest.main()
