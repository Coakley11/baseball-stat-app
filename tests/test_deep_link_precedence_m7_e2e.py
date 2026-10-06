"""Mobile M7 — end-to-end deep-link precedence through a real app run.

Complements ``test_deep_link_precedence_m7.py`` (fast unit coverage of the guard)
by driving the whole script with ``AppTest``: query params in, resolved
``active_page`` out, with a controlled workspace file on disk supplying a *stale*
saved page to compete with the deep link.

Self-cleaning (Mobile M7 item 8): the workspace file this writes is backed up in
``setUpClass`` and restored in ``tearDownClass``. Note the app's own autosave can
still write that path *after* teardown — that is production behavior, not the
test's. What matters for determinism is the other direction: every scenario
rewrites the controlled state in ``setUp``, so these tests never *depend* on
whatever happens to be on disk. Verified by running the file twice in a row
against a dirty leftover autosave; same results both times.
"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# A preset workspace id (suite_workspace.WORKSPACE_PRESETS) — arbitrary ids are
# clamped by workspace resolution, so an invented one would not isolate anything.
WS_ID = "guest"
WS_FILE = ROOT / "data" / "workspaces" / WS_ID / "baseball_user_state.json"
STALE_PAGE = "ML Predictions"


def _write_stale_workspace(page: str) -> None:
    WS_FILE.parent.mkdir(parents=True, exist_ok=True)
    WS_FILE.write_text(
        json.dumps(
            {
                "version": 1,
                "app": "baseball",
                "saved_at": "2026-01-01T00:00:00+00:00",
                "state": {
                    "active_page": page,
                    "main_sidebar_page": page,
                    "_suite_user_owned_page": page,
                    "_suite_last_persisted_page": page,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _run(active_page: str | None):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=300)
    if active_page is not None:
        at.query_params["active_page"] = active_page
    at.query_params["suite_workspace"] = WS_ID
    at.run()
    return at


def _state(at, key, default=None):
    try:
        return at.session_state[key]
    except Exception:
        return default


class DeepLinkEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._backup = None
        if WS_FILE.is_file():
            cls._backup = WS_FILE.read_bytes()
        cls._dir_created = not WS_FILE.parent.exists()

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._backup is not None:
            WS_FILE.write_bytes(cls._backup)
        elif WS_FILE.is_file():
            WS_FILE.unlink()
        if cls._dir_created and WS_FILE.parent.exists():
            shutil.rmtree(WS_FILE.parent, ignore_errors=True)

    def setUp(self) -> None:
        # Every scenario starts from the same stale saved page.
        _write_stale_workspace(STALE_PAGE)

    def test_deep_link_to_default_page_beats_stale_saved_page(self) -> None:
        """The M5-reported failure, end to end: saved page is ML Predictions, the
        deep link asks for the default page, and the deep link must win."""
        import streamlit_app  # noqa: F401  (import here so PAGE_OPTIONS is available)

        default_page = streamlit_app.PAGE_OPTIONS[0]
        at = _run(default_page)
        self.assertEqual([str(e.value)[:200] for e in at.exception], [])
        self.assertEqual(_state(at, "active_page"), default_page)
        self.assertEqual(_state(at, "main_sidebar_page"), default_page)

    def test_deep_link_to_non_default_page_beats_stale_saved_page(self) -> None:
        at = _run("Leaderboards")
        self.assertEqual([str(e.value)[:200] for e in at.exception], [])
        self.assertEqual(_state(at, "active_page"), "Leaderboards")

    def test_without_a_deep_link_the_saved_page_is_restored(self) -> None:
        """Restore stays the fallback when nothing explicit was requested.

        Asserted on main_sidebar_page -- the restored navigation selection. Since
        monetization, ML Predictions is a Pro page: for a Free session the gate
        routes through begin_page_run(), which sets active_page to the internal
        sentinel __MONETIZATION_GATE__ while the user is still, correctly, on ML
        Predictions. The restore itself is what this test is about.
        """
        at = _run(None)
        self.assertEqual([str(e.value)[:200] for e in at.exception], [])
        self.assertEqual(_state(at, "main_sidebar_page"), STALE_PAGE)
        self.assertIn(_state(at, "active_page"), {STALE_PAGE, "__MONETIZATION_GATE__"})

    def test_invalid_deep_link_falls_back_safely(self) -> None:
        """An unknown page value must not raise and must not strand the app on a
        page that does not exist; existing behavior coerces to the default."""
        import streamlit_app  # noqa: F401

        at = _run("Not A Real Page")
        self.assertEqual([str(e.value)[:200] for e in at.exception], [])
        self.assertIn(_state(at, "active_page"), set(streamlit_app.PAGE_OPTIONS))


if __name__ == "__main__":
    unittest.main()
