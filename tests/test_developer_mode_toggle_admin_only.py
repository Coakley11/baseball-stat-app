"""Developer Mode toggle must stay hidden for signed-out / non-admin users."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


class TestDeveloperModeToggleVisibility(unittest.TestCase):
    def test_toggle_source_gates_on_admin_eligibility(self) -> None:
        src = Path(__file__).resolve().parents[1] / "streamlit_app.py"
        text = src.read_text(encoding="utf-8")
        # Must not keep the old always-mounted policy.
        self.assertNotIn("Always mounted — auth/workspace must never hide this control", text)
        self.assertIn("developer_tools_workspace_eligible", text)
        # Gate appears before checkbox materialization.
        fn_start = text.index("def render_developer_mode_sidebar_toggle")
        fn_chunk = text[fn_start : fn_start + 2500]
        self.assertIn("developer_tools_workspace_eligible", fn_chunk)
        checkbox_idx = fn_chunk.find("checkbox(")
        self.assertGreater(checkbox_idx, 0)
        self.assertLess(
            fn_chunk.index("developer_tools_workspace_eligible"),
            checkbox_idx,
        )

    def test_auth_panel_accepts_flat_sidebar_kwargs(self) -> None:
        import inspect

        from suite_auth import render_auth_panel

        sig = inspect.signature(render_auth_panel)
        self.assertIn("show_signed_in_status", sig.parameters)
        self.assertIn("flat_sidebar", sig.parameters)


if __name__ == "__main__":
    unittest.main()
