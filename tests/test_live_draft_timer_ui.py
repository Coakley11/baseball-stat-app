"""Guard: live_draft_timer_ui must stay fragment-safe (no streamlit_app import)."""

from __future__ import annotations

import ast
import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock


class LiveDraftTimerUiImportGuardTests(unittest.TestCase):
    def test_source_has_no_streamlit_app_import(self) -> None:
        path = Path(__file__).resolve().parent.parent / "live_draft_timer_ui.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        banned = {"streamlit_app", "Streamlit_app"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], banned)
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], banned)

    def test_importing_module_does_not_load_streamlit_app(self) -> None:
        repo_root = str(Path(__file__).resolve().parent.parent)
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)

        real_import = importlib.import_module

        def guarded_import(name: str, package: str | None = None):  # type: ignore[no-untyped-def]
            root = (name or "").split(".")[0]
            if root in ("streamlit_app", "Streamlit_app"):
                raise AssertionError(f"live_draft_timer_ui must not import {name}")
            return real_import(name, package)

        with mock.patch("importlib.import_module", side_effect=guarded_import):
            if "live_draft_timer_ui" in sys.modules:
                del sys.modules["live_draft_timer_ui"]
            import live_draft_timer_ui  # noqa: F401


class LiveDraftTimerLogicTests(unittest.TestCase):
    def test_seconds_remaining_counts_down(self) -> None:
        from live_draft_timer_logic import live_draft_seconds_remaining

        room = {
            "status": "in_progress",
            "config": {"timer_seconds": 60},
            "timer_started_at": __import__("time").time() - 10,
        }
        remaining = live_draft_seconds_remaining(room)
        self.assertGreaterEqual(remaining, 49)
        self.assertLessEqual(remaining, 50)

    def test_current_slot_respects_index(self) -> None:
        from live_draft_timer_logic import live_draft_current_slot

        room = {
            "current_pick_index": 1,
            "pick_order": [{"Pick": 1, "Team": "A"}, {"Pick": 2, "Team": "B"}],
        }
        slot = live_draft_current_slot(room)
        self.assertEqual(slot["Team"], "B")

    def test_grace_skipped_when_timer_expired(self) -> None:
        import time

        from live_draft_timer_ui import _page_load_grace_active

        session = {"_live_draft_page_load_ts": time.time()}
        room = {
            "status": "in_progress",
            "config": {"timer_seconds": 60},
            "current_pick_index": 4,
            "timer_handled_index": -1,
            "timer_started_at": time.time() - 120,
        }
        self.assertFalse(_page_load_grace_active(session, room))


if __name__ == "__main__":
    unittest.main()
