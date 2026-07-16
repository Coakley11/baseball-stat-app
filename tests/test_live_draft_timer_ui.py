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

    def test_display_recomputes_from_deadline_each_call(self) -> None:
        import time

        from live_draft_timer_logic import live_draft_display_seconds, live_draft_seconds_remaining

        deadline = time.time() + 30
        room = {
            "status": "in_progress",
            "config": {"timer_seconds": 60},
            "timer_deadline": deadline,
            "timer_started_at": time.time() - 999,
        }
        r1 = live_draft_display_seconds(room)
        room["timer_deadline"] = deadline - 5
        r2 = live_draft_display_seconds(room)
        self.assertGreater(r1, r2)
        self.assertEqual(live_draft_seconds_remaining(room), r2)

    def test_timer_diagnostics_record_tick_metadata(self) -> None:
        import time

        from live_draft_timer_ui import LIVE_DRAFT_TIMER_DIAG_KEY, record_timer_diagnostics

        session: dict = {}
        room = {
            "status": "in_progress",
            "config": {"timer_seconds": 60},
            "timer_deadline": time.time() + 25,
            "current_pick_index": 2,
        }
        diag = record_timer_diagnostics(session, room, source="fragment_tick")
        self.assertIn("timer_deadline", diag)
        self.assertIn("computed_remaining", diag)
        self.assertTrue(session[LIVE_DRAFT_TIMER_DIAG_KEY]["timer_fragment_active"])

    def test_timer_should_not_run_during_start(self) -> None:
        from live_draft_safe_mode import timer_should_run
        from live_draft_start_progress import begin_live_draft_start

        session: dict = {}
        room = {
            "status": "in_progress",
            "config": {"timer_seconds": 60, "num_teams": 2, "picks_per_team": 5},
            "teams": ["A", "B"],
            "pick_order": [{"Pick": 1, "Team": "A"}],
            "draft_board": [],
            "current_pick_index": 0,
            "timer_deadline": __import__("time").time() + 60,
        }
        begin_live_draft_start(session)
        self.assertFalse(timer_should_run(session, room))

    def test_current_slot_respects_index(self) -> None:
        from live_draft_timer_logic import live_draft_current_slot

        room = {
            "current_pick_index": 1,
            "pick_order": [{"Pick": 1, "Team": "A"}, {"Pick": 2, "Team": "B"}],
        }
        slot = live_draft_current_slot(room)
        self.assertEqual(slot["Team"], "B")

    def test_render_timer_bar_mounts_recovery_fragment_when_expired(self) -> None:
        import time

        from live_draft_timer_ui import render_live_draft_timer_bar

        class _FakeSt:
            def __init__(self) -> None:
                self.captions: list[str] = []
                self.markdowns: list[str] = []
                self.fragment_called = False
                self.rerun_called = False

            def caption(self, text: str) -> None:
                self.captions.append(str(text))

            def markdown(self, text: str, **_kwargs: object) -> None:
                self.markdowns.append(str(text))

            def rerun(self) -> None:
                self.rerun_called = True

            def fragment(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
                self.fragment_called = True

                def deco(fn):  # type: ignore[no-untyped-def]
                    return fn

                return deco

        session: dict = {
            "_live_draft_render_trace_force": True,
            "_live_draft_page_owns_expired": True,
        }
        room = {
            "status": "in_progress",
            "config": {"timer_seconds": 60},
            "timer_deadline": time.time() - 5,
            "timer_started_at": time.time() - 120,
            "current_pick_index": 0,
            "timer_handled_index": -1,
        }
        fake = _FakeSt()
        with mock.patch("live_draft_timer_ui.timer_should_run", return_value=True, create=True):
            with mock.patch(
                "live_draft_safe_mode.timer_should_run",
                return_value=True,
            ):
                render_live_draft_timer_bar(fake, session, room)
        self.assertTrue(fake.fragment_called)
        self.assertFalse(fake.rerun_called)
        self.assertTrue(session.get("_live_draft_timer_expired_pending"))
        self.assertTrue(any("Processing expired pick" in c for c in fake.captions))

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

    def test_sidebar_timer_fragment_does_not_write_sidebar(self) -> None:
        import time

        from draft_ui import SIDEBAR_TIMER_REMAINING_KEY, refresh_sidebar_timer_session

        session = {
            "live_draft_room": {
                "status": "in_progress",
                "config": {"timer_seconds": 90},
                "current_pick_index": 0,
                "timer_deadline": time.time() + 45,
                "timer_started_at": time.time(),
            }
        }
        refresh_sidebar_timer_session(session)
        self.assertIn(SIDEBAR_TIMER_REMAINING_KEY, session)
        self.assertGreater(int(session[SIDEBAR_TIMER_REMAINING_KEY]), 0)


if __name__ == "__main__":
    unittest.main()
