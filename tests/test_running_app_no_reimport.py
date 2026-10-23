"""Live Draft helpers reach the running app without executing a second copy of the Streamlit script.

Inside the app the script is ``__main__``. ``importlib.import_module("streamlit_app")`` from a helper executed the
whole script again in the same run; the copy raised StreamlitDuplicateElementKey('main_sidebar_page'), the callers
swallowed it, and a Solo draft never left Ready on a server without the (gitignored) prewarm pool.
"""

from __future__ import annotations

import builtins
import re
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import running_app

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("live_draft_canonical_pool.py", "live_draft_ready_contract.py", "live_draft_fast_solo_start.py",
           "shared_draft_local_pool.py")
_real_import = builtins.__import__


def _no_app_import(name, *args, **kwargs):
    if name == "streamlit_app":
        raise AssertionError("imported streamlit_app while the app is running")
    return _real_import(name, *args, **kwargs)


def _fake_running_app(**attrs) -> types.ModuleType:
    main = types.ModuleType("__main__")
    main.__file__ = str(ROOT / "streamlit_app.py")
    for k, v in attrs.items():
        setattr(main, k, v)
    return main


class RunningAppModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._had_app = sys.modules.pop("streamlit_app", None)

    def tearDown(self) -> None:
        if self._had_app is not None:
            sys.modules["streamlit_app"] = self._had_app

    def test_inside_the_app_the_running_module_is_returned(self) -> None:
        main = _fake_running_app()
        with mock.patch.dict(sys.modules, {"__main__": main}), mock.patch("builtins.__import__", _no_app_import):
            self.assertIs(running_app.running_app_module(), main)
        self.assertNotIn("streamlit_app", sys.modules)

    def test_outside_the_app_it_is_imported_normally(self) -> None:
        other = types.ModuleType("__main__")
        other.__file__ = "pytest_runner.py"
        sentinel = types.ModuleType("streamlit_app")
        with mock.patch.dict(sys.modules, {"__main__": other}), \
                mock.patch("importlib.import_module", return_value=sentinel) as imp:
            self.assertIs(running_app.running_app_module(), sentinel)
        imp.assert_called_once_with("streamlit_app")

    def test_live_draft_canonical_pool_uses_the_running_apps_builder(self) -> None:
        import live_draft_canonical_pool as lcp

        calls = []
        pool = pd.DataFrame({"fullName": ["A"], "Primary Position": ["OF"]})

        def builder(*args, **kwargs):
            calls.append(args)
            return pool

        main = _fake_running_app(get_cached_unified_projection_pool=builder,
                                 get_cached_unified_projection_pool_live=builder)
        with mock.patch.dict(sys.modules, {"__main__": main}), mock.patch("builtins.__import__", _no_app_import):
            lcp.load_canonical_unified_pool({})
        self.assertTrue(calls, "the running app's cached pool builder was used")
        self.assertNotIn("streamlit_app", sys.modules)

    def test_live_draft_modules_never_import_streamlit_app_by_name(self) -> None:
        for name in MODULES:
            src = (ROOT / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r'import_module\(\s*["\']streamlit_app["\']|^\s*(from streamlit_app import|import streamlit_app)',
                                        src, re.M), name)


if __name__ == "__main__":
    unittest.main()
