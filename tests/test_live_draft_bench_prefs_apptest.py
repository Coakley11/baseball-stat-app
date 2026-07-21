"""Bench=0 persists by account — not widget fallback 5."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from user_page_preferences import (
    collect_live_draft_setup_settings,
    live_draft_setup_number_default,
)

_RENDER_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "live_draft_bench_prefs_render_apptest.py"
)


class LiveDraftBenchPrefsTests(unittest.TestCase):
    def test_session_bench_zero_beats_fallback(self) -> None:
        session = {"live_slot_bench": 0}
        self.assertEqual(live_draft_setup_number_default(session, "live_slot_bench", 5), 0)

    def test_persisted_bench_zero_beats_fallback(self) -> None:
        session = {"auth_user_id": "user:daniel", "workspace_id": "ws1"}
        with patch(
            "user_page_preferences.get_user_page_preferences",
            return_value={"live_slot_bench": 0, "live_draft_picks_per_team": 5},
        ):
            self.assertEqual(live_draft_setup_number_default(session, "live_slot_bench", 5), 0)

    def test_collect_settings_includes_bench_zero(self) -> None:
        session = {
            "live_slot_bench": 0,
            "live_draft_picks_per_team": 5,
            "live_slot_c": 1,
            "live_slot_1b": 1,
            "live_slot_2b": 1,
            "live_slot_3b": 1,
            "live_slot_ss": 1,
            "live_slot_of": 3,
            "live_slot_dh": 0,
            "live_slot_p": 0,
        }
        settings = collect_live_draft_setup_settings(session)
        self.assertIn("live_slot_bench", settings)
        self.assertEqual(int(settings["live_slot_bench"]), 0)

    def test_rendered_bench_zero_survives_save_and_reload(self) -> None:
        from streamlit.testing.v1 import AppTest

        prefs_store: dict = {}

        def _save(uid, wid, page_key, settings, **kwargs):  # noqa: ANN001
            prefs_store[(uid, wid, page_key)] = dict(settings)
            session = kwargs.get("session") or {}
            pfs = session.setdefault("page_filter_state", {})
            pfs["_user_page_preferences"] = pfs.get("_user_page_preferences") or {}
            pfs["_user_page_preferences"][page_key] = {
                "user_id": uid,
                "workspace_id": wid,
                "settings": dict(settings),
            }
            return {"ok": True}

        def _get(uid, wid, page_key, **kwargs):  # noqa: ANN001
            session = kwargs.get("session") or {}
            pfs = session.get("page_filter_state") or {}
            block = (pfs.get("_user_page_preferences") or {}).get(page_key)
            if isinstance(block, dict) and isinstance(block.get("settings"), dict):
                return dict(block["settings"])
            stored = prefs_store.get((uid, wid, page_key))
            return dict(stored) if stored else {}

        with patch("user_page_preferences.save_user_page_preferences", side_effect=_save):
            with patch("user_page_preferences.get_user_page_preferences", side_effect=_get):
                at = AppTest.from_file(str(_RENDER_FIXTURE), default_timeout=30)
                at.session_state["live_slot_bench"] = 0
                at.run()
                save = [b for b in at.button if b.key == "bench_save_prefs"]
                save[0].click().run()
                self.assertTrue("_bench_saved" in at.session_state and at.session_state["_bench_saved"])

                reload_btn = [b for b in at.button if b.key == "bench_reload_prefs"]
                reload_btn[0].click().run()
                self.assertFalse(at.exception)
                markdown = " ".join(str(m.value) for m in at.markdown)
                self.assertIn("BENCH_AFTER_RELOAD=0", markdown)
                self.assertNotIn("BENCH_AFTER_RELOAD=5", markdown)


if __name__ == "__main__":
    unittest.main()
