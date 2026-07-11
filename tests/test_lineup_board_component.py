"""Packaging tests for the Fantasy Lineup board Streamlit component."""

from __future__ import annotations

import unittest
from pathlib import Path

from lineup_board_component import (
    component_frontend_ready,
    get_component_frontend_dir,
)


class LineupBoardComponentPackagingTests(unittest.TestCase):
    def test_frontend_dir_is_module_relative(self) -> None:
        frontend = get_component_frontend_dir()
        module_dir = Path(__file__).resolve().parents[1] / "lineup_board_component" / "frontend"
        self.assertEqual(frontend.resolve(), module_dir.resolve())

    def test_index_html_exists_at_declared_path(self) -> None:
        self.assertTrue(component_frontend_ready())
        index = get_component_frontend_dir() / "index.html"
        self.assertTrue(index.is_file())
        content = index.read_text(encoding="utf-8")
        self.assertIn("streamlit:componentReady", content)
        self.assertIn("streamlit:render", content)
        self.assertIn("event.data.args", content)

    def test_frontend_initializes_streamlit_handshake(self) -> None:
        content = (get_component_frontend_dir() / "index.html").read_text(encoding="utf-8")
        self.assertIn('sendMessage("streamlit:componentReady"', content)
        self.assertIn("setFrameHeight", content)


if __name__ == "__main__":
    unittest.main()
