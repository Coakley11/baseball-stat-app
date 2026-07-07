"""Regression tests for settings on_change trace wrapper signature."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from settings_persistence_trace import record_onchange


ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_APP = ROOT / "streamlit_app.py"


class RecordSettingsOnchangeTests(unittest.TestCase):
    def test_record_onchange_accepts_deferred_save_flags(self) -> None:
        session: dict = {}
        with patch("settings_persistence_trace._dev_trace_enabled", return_value=True):
            record_onchange(
                session,
                "Draft Assistant Simulator",
                handler="_draft_assistant_settings_changed",
                save_page_state=False,
                force_save=False,
                reason="draft_assistant_settings_changed_deferred",
            )
        trace = session.get("_settings_onchange_trace")
        self.assertIsInstance(trace, list)
        self.assertTrue(trace)
        last = trace[-1]
        self.assertFalse(last.get("save_page_state_called"))
        self.assertFalse(last.get("force_save_called"))

    def test_record_settings_onchange_wrapper_accepts_force_save_keyword(self) -> None:
        source = STREAMLIT_APP.read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_record_settings_onchange"
        )
        param_names = [arg.arg for arg in fn.args.args]
        kwonly = [arg.arg for arg in fn.args.kwonlyargs]
        self.assertIn("force_save", kwonly)
        self.assertIn("save_page_state", kwonly)

        # Draft Assistant deferred path must pass force_save=False without TypeError.
        self.assertIn("force_save=False", source)
        self.assertIn("_draft_assistant_settings_changed(*_args, **_kwargs)", source)
        self.assertIn("_draft_assistant_position_sync_changed(*_args, **_kwargs)", source)


if __name__ == "__main__":
    unittest.main()
