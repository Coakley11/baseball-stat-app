"""Fast startup import contract tests (no full streamlit_app import)."""

from __future__ import annotations

import ast
import importlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_APP = ROOT / "streamlit_app.py"


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

    def test_streamlit_player_trade_bridge_import_contract(self) -> None:
        from player_trade_constants import (
            TRADE_ACTION_ACQUIRE,
            TRADE_ACTION_TRADE_AWAY,
            TRADE_FLOW_SESSION_KEY,
        )
        import player_trade_bridge
        from player_trade_bridge import (
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
        self.assertTrue(hasattr(player_trade_bridge, "start_player_trade_action"))
        self.assertTrue(hasattr(player_trade_bridge, "resolve_active_league_player_trade_eligibility"))

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
        for mod in ("workflow_sidebar", "page_transfers", "app_tutorial", "player_actions", "player_trade_bridge"):
            importlib.import_module(mod)
        from player_trade_bridge import TRADE_FLOW_SESSION_KEY

        self.assertTrue(TRADE_FLOW_SESSION_KEY)

    def test_streamlit_app_parses_and_imports_from_clean_checkout(self) -> None:
        source = STREAMLIT_APP.read_text(encoding="utf-8")
        ast.parse(source, filename=str(STREAMLIT_APP))
        compile(source, str(STREAMLIT_APP), "exec")
        self.assertIn("import player_trade_bridge", source)
        self.assertIn("from player_trade_constants import", source)
        self.assertNotIn("resolve_active_league_player_trade_eligibility,", source.split("import projection_calibration", 1)[0])


if __name__ == "__main__":
    unittest.main()
