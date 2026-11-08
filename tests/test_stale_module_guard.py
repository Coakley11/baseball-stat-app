"""D4J Dev start-up crash, 2026-11-08: ``AttributeError: module 'action_icons' has no attribute
'DRAFT_PLAYER'`` right after the de44bdf push, although action_icons.py on disk defined it.

Streamlit Cloud pulls a push into the running process: the main script is re-read, but imported
modules stay loaded from the previous release. These tests reproduce that with Streamlit's real
script runner (modules persist across runs in one process, as on Cloud) and the real eaf3d03 and
de44bdf versions of action_icons.py, then prove the guard fixes it. A second group imports the
real action_icons and checks every ``_icons.NAME`` the app uses.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
OLD_ICONS = """\
\"\"\"action_icons as released in eaf3d03 (no DRAFT_PLAYER).\"\"\"
ADD_TO_QUEUE = ":material/playlist_add:"
WATCHLIST = ":material/visibility:"
"""


def _main(app_dir: str, guard: bool) -> None:
    import sys

    import streamlit as st

    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    if guard:
        import stale_module_guard

        stale_module_guard.refresh_stale_app_modules(app_dir, force=True)
    import action_icons as _icons

    if open(app_dir + "/phase.txt").read().strip() == "new":  # the new streamlit_app.py line 11018
        icons = {"add_draft_queue": _icons.ADD_TO_QUEUE, "draft_player": _icons.DRAFT_PLAYER}
    else:
        icons = {"add_draft_queue": _icons.ADD_TO_QUEUE}
    st.markdown("icons: " + " ".join(sorted(icons.values())))


@unittest.skipIf(sys.dont_write_bytecode, "needs .pyc files, as on Streamlit Cloud")
class InPlacePullTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="stale_mod_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(sys.modules.pop, "action_icons", None)
        self.addCleanup(lambda: sys.path.remove(self.dir) if self.dir in sys.path else None)
        sys.modules.pop("action_icons", None)
        Path(self.dir, "action_icons.py").write_text(OLD_ICONS, encoding="utf-8")
        Path(self.dir, "phase.txt").write_text("old", encoding="utf-8")

    def _pull_new_release(self) -> None:
        time.sleep(1.1)  # a later mtime, as a git pull gives
        shutil.copyfile(ROOT / "action_icons.py", Path(self.dir, "action_icons.py"))
        Path(self.dir, "phase.txt").write_text("new", encoding="utf-8")

    def _run_release_then_pull(self, guard: bool) -> AppTest:
        at = AppTest.from_function(_main, default_timeout=30, kwargs={"app_dir": self.dir, "guard": guard})
        at.run()
        self.assertFalse(at.exception)
        self._pull_new_release()
        at.run()
        return at

    def test_without_the_guard_the_exact_d4j_crash_happens(self) -> None:
        at = self._run_release_then_pull(guard=False)
        self.assertTrue(at.exception)
        self.assertIn("has no attribute 'DRAFT_PLAYER'", at.exception[0].value)

    def test_with_the_guard_the_new_module_loads(self) -> None:
        at = self._run_release_then_pull(guard=True)
        self.assertFalse(at.exception)
        self.assertIn("🔴", at.markdown[0].value)

    def test_unchanged_modules_are_not_reloaded(self) -> None:
        import stale_module_guard

        at = AppTest.from_function(_main, default_timeout=30, kwargs={"app_dir": self.dir, "guard": True})
        at.run()
        at.run()
        self.assertEqual(stale_module_guard.stale_app_modules(self.dir), [])


class IconRegistrationTests(unittest.TestCase):
    """Every ``_icons.NAME`` / ``action_icons.NAME`` used by the app exists in the real module."""

    def test_every_icon_the_app_uses_is_defined(self) -> None:
        import action_icons

        missing: dict[str, list[str]] = {}
        for path in ROOT.glob("*.py"):
            src = path.read_text(encoding="utf-8", errors="replace")
            if "action_icons" not in src:
                continue
            tree = ast.parse(src)
            aliases = {"action_icons"}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    aliases |= {a.asname or a.name for a in node.names if a.name == "action_icons"}
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
                    if not hasattr(action_icons, node.attr):
                        missing.setdefault(path.name, []).append(node.attr)
                if isinstance(node, ast.ImportFrom) and node.module == "action_icons":
                    for a in node.names:
                        if a.name != "*" and not hasattr(action_icons, a.name):
                            missing.setdefault(path.name, []).append(a.name)
        self.assertEqual(missing, {})

    def test_player_action_icons_are_colourful_emoji(self) -> None:
        import action_icons as _icons

        for name in ("ADD_TO_QUEUE", "WATCHLIST", "DRAFT_PLAYER", "TRADE", "ACQUIRE", "PLAN_ADD", "PLAN_DROP"):
            value = getattr(_icons, name)
            self.assertTrue(value and not value.startswith(":material/"), name)

    def test_the_app_refreshes_stale_modules_before_importing_any(self) -> None:
        src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertLess(src.index("refresh_stale_app_modules()"), src.index("import action_icons as _icons"))
        self.assertLess(src.index("refresh_stale_app_modules()"), src.index("import streamlit as st"))

    def test_streamlit_app_compiles_and_imports_icons_in_a_fresh_process(self) -> None:
        code = (
            "import ast, action_icons, stale_module_guard;"
            "ast.parse(open('streamlit_app.py', encoding='utf-8').read());"
            "print(action_icons.DRAFT_PLAYER, stale_module_guard.refresh_stale_app_modules(force=True))"
        )
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        self.assertIn("🔴 []", out.stdout)


if __name__ == "__main__":
    unittest.main()
