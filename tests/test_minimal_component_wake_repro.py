"""Packaging tests for minimal component wake repro."""

from __future__ import annotations

import unittest
from pathlib import Path


class MinimalWakeReproTests(unittest.TestCase):
    def test_frontend_exists(self) -> None:
        index = (
            Path(__file__).resolve().parents[1]
            / "minimal_wake_repro_component"
            / "frontend"
            / "index.html"
        )
        self.assertTrue(index.is_file())
        content = index.read_text(encoding="utf-8")
        self.assertIn("streamlit:setComponentValue", content)
        self.assertIn("streamlit:componentReady", content)
        self.assertIn("repro-countdown", content)

    def test_entrypoint_exists(self) -> None:
        entry = Path(__file__).resolve().parents[1] / "minimal_component_wake_repro.py"
        self.assertTrue(entry.is_file())
        content = entry.read_text(encoding="utf-8")
        self.assertIn("on_change", content)
        self.assertIn("minimal_wake_repro", content)
        self.assertNotIn("streamlit_app", content)


if __name__ == "__main__":
    unittest.main()
