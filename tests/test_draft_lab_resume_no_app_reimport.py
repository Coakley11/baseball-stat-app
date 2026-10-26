"""The Draft Lab resume never imports ``streamlit_app``.

Inside the running app the script is ``__main__``; importing ``streamlit_app`` from a helper executes a second
copy of the whole script in the same run. On the first Draft Lab Continue after a server start that registered the
sidebar page radio twice (StreamlitDuplicateElementKey 'main_sidebar_page'); a refresh worked because the second
copy was then cached in sys.modules.
"""

from __future__ import annotations

import builtins
import re
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import draft_lab_resume

ROOT = Path(__file__).resolve().parents[1]
_real_import = builtins.__import__


def _no_app_import(name, *args, **kwargs):
    if name == "streamlit_app":
        raise AssertionError("draft_lab_resume imported streamlit_app")
    return _real_import(name, *args, **kwargs)


class NoAppReimportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._had_app = sys.modules.pop("streamlit_app", None)

    def tearDown(self) -> None:
        if self._had_app is not None:
            sys.modules["streamlit_app"] = self._had_app

    def test_uses_the_running_apps_own_push(self) -> None:
        calls = []
        main = types.ModuleType("__main__")
        main.live_draft_push_analysis_to_session = lambda room: calls.append(room) or True
        room = {"draft_room_id": "R1", "status": "complete"}
        with mock.patch.dict(sys.modules, {"__main__": main}), mock.patch("builtins.__import__", _no_app_import):
            self.assertTrue(draft_lab_resume._push_analysis_to_session(room))
        self.assertEqual(calls, [room])
        self.assertNotIn("streamlit_app", sys.modules)

    def test_outside_the_app_uses_the_shared_handoff(self) -> None:
        main = types.ModuleType("__main__")
        room = {"draft_room_id": "R2", "status": "complete"}
        with mock.patch.dict(sys.modules, {"__main__": main}), \
                mock.patch("draft_lab_handoff.push_completed_live_draft_to_lab", return_value=True) as push, \
                mock.patch("builtins.__import__", _no_app_import):
            self.assertTrue(draft_lab_resume._push_analysis_to_session(room))
        self.assertIs(push.call_args.args[1], room)
        self.assertNotIn("streamlit_app", sys.modules)

    def test_module_source_has_no_streamlit_app_import(self) -> None:
        src = (ROOT / "draft_lab_resume.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^\s*(from streamlit_app import|import streamlit_app)", src, re.M))


if __name__ == "__main__":
    unittest.main()
