"""Guard: exclusive active_page if/elif router must stay syntactically valid."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_APP = ROOT / "streamlit_app.py"


class ExclusivePageRouterTests(unittest.TestCase):
    def test_streamlit_app_compiles(self) -> None:
        source = STREAMLIT_APP.read_text(encoding="utf-8")
        compile(source, str(STREAMLIT_APP), "exec")
        ast.parse(source)

    def test_active_page_branches_are_contiguous_if_elif(self) -> None:
        lines = STREAMLIT_APP.read_text(encoding="utf-8").splitlines()
        branches = [
            (i + 1, line)
            for i, line in enumerate(lines)
            if line.startswith("if active_page ==") or line.startswith("elif active_page ==")
        ]
        self.assertGreaterEqual(len(branches), 10)
        self.assertTrue(branches[0][1].startswith("if active_page =="))
        for lineno, line in branches[1:]:
            self.assertTrue(
                line.startswith("elif active_page =="),
                msg=f"line {lineno} must be elif, got: {line[:80]}",
            )
        # No top-level def between consecutive branches
        idxs = [i for i, line in enumerate(lines) if line.startswith("if active_page ==") or line.startswith("elif active_page ==")]
        for a, b in zip(idxs, idxs[1:]):
            for i in range(a + 1, b):
                self.assertFalse(
                    lines[i].startswith("def "),
                    msg=f"def at line {i+1} interrupts router between {a+1} and {b+1}",
                )

    def test_required_pages_present(self) -> None:
        text = STREAMLIT_APP.read_text(encoding="utf-8")
        for needle in (
            'if active_page == "Historical Explorer":',
            'elif active_page == "Career Totals":',
            'elif active_page == "Comparison Tool":',
            'elif active_page == "Live Draft Room":',
            'elif active_page == "Draft Room Simulator":',
        ):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
