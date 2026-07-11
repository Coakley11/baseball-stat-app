"""Fast startup import contract tests (no full streamlit_app import)."""

from __future__ import annotations

import unittest


class PlayerTradeStartupTests(unittest.TestCase):
    def test_player_trade_constants_are_import_safe(self) -> None:
        from player_trade_constants import (
            TRADE_ACTION_ACQUIRE,
            TRADE_ACTION_TRADE_AWAY,
            TRADE_FLOW_SESSION_KEY,
        )

        self.assertEqual(TRADE_ACTION_ACQUIRE, "acquire")
        self.assertEqual(TRADE_ACTION_TRADE_AWAY, "trade_away")
        self.assertTrue(TRADE_FLOW_SESSION_KEY)

    def test_player_trade_bridge_imports_without_streamlit_app(self) -> None:
        from player_trade_bridge import (
            TRADE_ACTION_ACQUIRE,
            complete_trade_acquire_flow,
            format_roster_context_label,
            player_trade_shortcut_eligible,
            start_trade_acquire_flow,
        )

        self.assertEqual(TRADE_ACTION_ACQUIRE, "acquire")
        self.assertTrue(callable(complete_trade_acquire_flow))
        self.assertTrue(callable(format_roster_context_label))
        self.assertTrue(callable(player_trade_shortcut_eligible))
        self.assertTrue(callable(start_trade_acquire_flow))

    def test_player_trade_context_exports_streamlit_contract(self) -> None:
        import player_trade_context as module

        required = {
            "TRADE_ACTION_ACQUIRE",
            "TRADE_ACTION_TRADE_AWAY",
            "TRADE_FLOW_SESSION_KEY",
            "complete_trade_acquire_flow",
            "format_roster_context_label",
            "player_trade_shortcut_eligible",
            "start_trade_acquire_flow",
        }
        missing = sorted(name for name in required if not hasattr(module, name))
        self.assertEqual(missing, [])
        self.assertTrue(str(module.__file__).endswith("player_trade_context.py"))

    def test_streamlit_prefix_import_chain_passes(self) -> None:
        import importlib

        for mod in ("workflow_sidebar", "page_transfers", "app_tutorial", "player_actions", "player_trade_bridge"):
            importlib.import_module(mod)
        from player_trade_bridge import TRADE_FLOW_SESSION_KEY

        self.assertTrue(TRADE_FLOW_SESSION_KEY)


if __name__ == "__main__":
    unittest.main()
