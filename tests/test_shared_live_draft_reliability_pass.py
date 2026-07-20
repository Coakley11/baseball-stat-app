"""Shared Live Draft reliability: pd panel, auto-picking once, accent filter, save on_click."""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


class TestDecisionPanelNoLocalPandasImport(unittest.TestCase):
    def test_no_function_local_import_pandas_as_pd(self) -> None:
        src = (ROOT / "live_draft_room_ui.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name != "render_draft_decision_panel":
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        self.assertNotEqual(alias.asname or alias.name, "pd")
                        self.assertFalse(alias.name.startswith("pandas"))
                if isinstance(child, ast.ImportFrom) and (child.module or "").startswith("pandas"):
                    self.fail("function-local pandas import in render_draft_decision_panel")

    def test_decision_panel_renders_markdown_rows_without_error(self) -> None:
        from live_draft_room_ui import render_draft_decision_panel

        st = MagicMock()
        session: dict = {}
        tracker = {
            "filled": 1,
            "target": 10,
            "lines": [
                {"position": "3B", "filled": True},
                {"position": "SS", "filled": False},
            ],
            "gaps": ["SS"],
        }
        available = pd.DataFrame(
            [
                {"fullName": "A", "primaryPos": "SS", "Scarcity Score": 0.7},
            ]
        )
        room = {
            "draft_board": [
                {"fullName": "José Ramírez", "Primary Position": "3B", "playerID": "jram01"},
            ]
        }
        # Must not raise UnboundLocalError on pd.
        render_draft_decision_panel(st, session, tracker=tracker, available_df=available, room=room)
        md = " ".join(str(c.args[0]) for c in st.markdown.call_args_list if c.args)
        self.assertIn("3B", md)
        self.assertIn("SS", md)


class TestAutoPickingSingleSource(unittest.TestCase):
    def test_timer_static_does_not_paint_auto_picking(self) -> None:
        from live_draft_timer_ui import _render_timer_static

        st = MagicMock()
        room = {"status": "in_progress", "timer_deadline": 0, "current_pick_index": 0}
        session: dict = {}
        _render_timer_static(st, session, room, source="static")
        md = " ".join(str(c.args[0]) for c in st.markdown.call_args_list if c.args)
        caps = " ".join(str(c.args[0]) for c in st.caption.call_args_list if c.args)
        self.assertNotIn("Auto-picking", md)
        self.assertNotIn("Auto-picking", caps)

    def test_on_clock_emits_single_auto_picking(self) -> None:
        from live_draft_on_clock_ui import _emit_primary_auto_picking_status

        st = MagicMock()
        session: dict = {"visible_auto_picking_status_count": 0}
        _emit_primary_auto_picking_status(st, session)
        self.assertEqual(session["visible_auto_picking_status_count"], 1)
        caps = [str(c.args[0]) for c in st.caption.call_args_list if c.args]
        self.assertEqual(sum(1 for c in caps if "Auto-picking" in c), 1)


class TestDraftedAccentFilter(unittest.TestCase):
    def test_jose_ramirez_excluded_when_accents_differ(self) -> None:
        from live_draft_ui_cache import filter_df_excluding_drafted

        room = {
            "draft_board": [
                {"fullName": "José Ramírez", "playerID": "jram01"},
            ]
        }
        recs = pd.DataFrame(
            [
                {"fullName": "Jose Ramirez", "playerID": "other"},
                {"fullName": "Francisco Lindor", "playerID": "lindor"},
            ]
        )
        out = filter_df_excluding_drafted(recs, room)
        names = [str(x) for x in out["fullName"].tolist()]
        self.assertNotIn("Jose Ramirez", names)
        self.assertIn("Francisco Lindor", names)


class TestSaveContinueOnClick(unittest.TestCase):
    def test_commissioner_actions_use_on_click(self) -> None:
        src = (ROOT / "live_draft_control_center_ui.py").read_text(encoding="utf-8")
        self.assertIn("on_save_continue_later_click", src)
        self.assertIn("on_click=on_save_continue_later_click", src)
        self.assertIn("Saving draft for later", src)

    def test_process_pending_save_continue_exists(self) -> None:
        from live_draft_resumable_slot import (
            PENDING_SAVE_CONTINUE_KEY,
            on_save_continue_later_click,
            process_pending_save_continue,
        )

        self.assertTrue(callable(on_save_continue_later_click))
        self.assertTrue(callable(process_pending_save_continue))
        self.assertEqual(PENDING_SAVE_CONTINUE_KEY, "_live_draft_pending_save_continue")


class TestAutoPickUsesConfiguredRule(unittest.TestCase):
    def test_autopick_scores_configured_rule(self) -> None:
        src = inspect.getsource(
            __import__("live_draft_autopick", fromlist=["live_draft_auto_pick"]).live_draft_auto_pick
        )
        self.assertIn("rule_key", src)
        self.assertNotIn('using top recommendation', src)


class TestLiveQueueDragEnabled(unittest.TestCase):
    def test_live_prefix_drag_not_disabled(self) -> None:
        src = (ROOT / "draft_ui.py").read_text(encoding="utf-8")
        self.assertNotIn(
            'not str(key_prefix).startswith("live")',
            src,
        )
        self.assertIn("_enable_drag = len(queue) >= 2", src)


if __name__ == "__main__":
    unittest.main()
