"""Ensure root requirements.txt pins Starlette for Streamlit gzip compatibility."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "requirements.txt"


class RequirementsStarlettePinTests(unittest.TestCase):
    def test_root_requirements_pins_starlette_0521(self) -> None:
        text = REQ.read_text(encoding="utf-8")
        self.assertIn("starlette==0.52.1", text)
        self.assertIn("streamlit==1.59.1", text)


if __name__ == "__main__":
    unittest.main()
