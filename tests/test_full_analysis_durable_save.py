"""Full analysis is reported as sent only after Command Center storage accepted it."""

from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from suite_analytical_question import submit_analytical_question


def _store(*, resume_ok: bool = True, saved_ok: bool = True) -> types.ModuleType:
    calls: dict[str, list] = {"resume": [], "saved": []}

    def upsert_resume_item(app, key, **kw):
        if not resume_ok:
            raise OSError("resume store down")
        calls["resume"].append((app, key, kw))

    def upsert_saved_item(app, item_type, key, **kw):
        if not saved_ok:
            raise OSError("saved-item store down")
        calls["saved"].append((app, item_type, key))
        return {"write_mode": "upsert"}

    mod = types.ModuleType("suite_storage")
    mod.upsert_resume_item = upsert_resume_item
    mod.upsert_saved_item = upsert_saved_item
    mod.calls = calls
    return mod


def _send(session: dict, store: types.ModuleType, activity: list) -> dict:
    with mock.patch.dict(sys.modules, {"suite_storage": store}), \
            mock.patch("suite_storage_supabase.upsert_resume_item", side_effect=RuntimeError("Supabase is not configured")), \
            mock.patch("suite_activity_client.record_activity", side_effect=lambda *a, **k: activity.append((a, k))):
        return submit_analytical_question(
            source_app="baseball",
            source_page="Historical Explorer",
            question="Who led the majors in HR from 2000 to 2010?",
            context={"page": "Historical Explorer", "sort_stat": "HR"},
            session_state=session,
        )


class DurableSaveTests(unittest.TestCase):
    def test_rejected_continue_card_is_a_failure_with_nothing_partial(self) -> None:
        session: dict = {}
        activity: list = []
        down = _store(resume_ok=False)
        result = _send(session, down, activity)
        self.assertTrue(result["save_failed"])
        self.assertEqual(activity, [], "no activity card for a send that was not saved")
        self.assertEqual(down.calls["saved"], [], "no context blob without its Continue card")
        self.assertNotIn("_ami_last_send", session, "the dedup marker is not spent")

    def test_rejected_context_blob_is_a_failure(self) -> None:
        session: dict = {}
        activity: list = []
        result = _send(session, _store(saved_ok=False), activity)
        self.assertTrue(result["save_failed"])
        self.assertEqual(activity, [])
        self.assertNotIn("_ami_last_send", session)

    def test_retry_after_failure_saves_once_then_dedups(self) -> None:
        session: dict = {}
        activity: list = []
        _send(session, _store(resume_ok=False), activity)
        up = _store()
        retry = _send(session, up, activity)
        self.assertFalse(retry["save_failed"])
        self.assertFalse(retry["duplicate"])
        self.assertEqual(len(up.calls["resume"]), 1)
        self.assertEqual(up.calls["resume"][0][0], "applied_intelligence")
        self.assertEqual(len(activity), 1)
        self.assertEqual(session["_ami_last_send"]["question"], "Who led the majors in HR from 2000 to 2010?")

        again = _send(session, up, activity)
        self.assertTrue(again["duplicate"])
        keys = {key for _app, key, _kw in up.calls["resume"]}
        self.assertEqual(len(keys), 1, "a repeat press updates the same Continue card, never a second one")


class FullAnalysisButtonTests(unittest.TestCase):
    def test_save_failed_result_shows_failure_not_success(self) -> None:
        from ami_assistant import ui

        st = types.SimpleNamespace(session_state={})
        ui._send_full_analysis(st, lambda q, p: {"save_failed": True, "duplicate": False},
                               {"question": "Q", "page": "Career Totals"})
        self.assertEqual(st.session_state[ui.FULL_ANALYSIS_KEY], {"question": "Q", "failed": True})


if __name__ == "__main__":
    unittest.main()
