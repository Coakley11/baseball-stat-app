"""Persistent Baseball sidebar chrome — visible signed out and signed in."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


class PersistentSidebarChromeTests(unittest.TestCase):
    def test_streamlit_resets_sidebar_guards_unconditionally(self) -> None:
        source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("reset_sidebar_run_guards(st.session_state)", source)
        # Must not be gated on __main__ only (breaks some Streamlit entry paths).
        idx = source.index("reset_sidebar_run_guards(st.session_state)")
        preamble = source[max(0, idx - 400) : idx]
        self.assertNotIn('if __name__ == "__main__":', preamble)

    def test_developer_toggle_does_not_gate_on_workspace_eligible(self) -> None:
        source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        start = source.index("def render_developer_mode_sidebar_toggle")
        end = source.index("\ndef migrate_legacy_widget_keys", start)
        fn = source[start:end]
        self.assertNotIn("developer_tools_workspace_eligible", fn)

    def test_portfolio_sidebar_enabled_by_default(self) -> None:
        from portfolio_polish import portfolio_sidebar_ui_enabled

        with patch.dict("os.environ", {}, clear=False):
            # Ensure default path when unset.
            import os

            os.environ.pop("PORTFOLIO_CAPTURE_UI", None)
            self.assertTrue(portfolio_sidebar_ui_enabled())

    def test_chrome_order_before_account_and_choose_page(self) -> None:
        source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        chrome = source.index("_render_baseball_sidebar_chrome(st)")
        # Find the actual call cluster after chrome (not earlier mentions in helpers).
        portfolio = source.index("pp.render_sidebar_toggle(st)", chrome)
        dev = source.index("render_developer_mode_sidebar_toggle()", chrome)
        account = source.index("render_baseball_account_sidebar(st)", chrome)
        choose = source.index('st.sidebar.radio(\n    "Choose Page"', chrome)
        self.assertLess(chrome, portfolio)
        self.assertLess(portfolio, dev)
        self.assertLess(dev, account)
        self.assertLess(account, choose)

    def test_command_center_link_renders_after_simulated_signin_rerun(self) -> None:
        from suite_command_center_link import render_command_center_sidebar_link
        from suite_sidebar_run import reset_sidebar_run_guards

        st = MagicMock()
        st.session_state = {}
        reset_sidebar_run_guards(st.session_state)
        render_command_center_sidebar_link(st)
        self.assertTrue(st.sidebar.link_button.called)
        # Next script run after auth.
        st.sidebar.link_button.reset_mock()
        reset_sidebar_run_guards(st.session_state)
        render_command_center_sidebar_link(st)
        self.assertTrue(st.sidebar.link_button.called)


if __name__ == "__main__":
    unittest.main()
