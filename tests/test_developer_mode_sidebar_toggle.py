"""Smoke/regression tests for Developer Mode sidebar toggle idempotency."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DeveloperModeSidebarToggleTests(unittest.TestCase):
    def test_single_call_site_in_streamlit_app(self) -> None:
        source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == "render_developer_mode_sidebar_toggle":
                calls += 1
        self.assertEqual(calls, 1)

    def test_render_function_claims_guard_before_checkbox(self) -> None:
        source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("claim_sidebar_render(st.session_state, GUARD_DEV_TOGGLE)", source)
        self.assertIn("dev_mode_checkbox_materialized()", source)
        self.assertIn("st.sidebar.checkbox(\n        \"Developer Mode\"", source)
        claim_idx = source.index("claim_sidebar_render(st.session_state, GUARD_DEV_TOGGLE)")
        checkbox_idx = source.index("st.sidebar.checkbox(\n        \"Developer Mode\"")
        self.assertLess(claim_idx, checkbox_idx)


if __name__ == "__main__":
    unittest.main()
