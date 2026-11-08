"""Draft Strategy Assistant page (B3): queue, save, load, update, delete through the real widgets.

The store (draft_strategy_store) is tested on its own; this drives the page with AppTest and a
temporary strategy file, so no workspace or account data is touched.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

SCRIPT = '''
import streamlit as st
from draft_strategy_ui import render_draft_strategy_page

if "draft_queue" not in st.session_state:
    st.session_state["draft_queue"] = list(st.session_state.get("_seed_queue") or [])
render_draft_strategy_page(st, st.session_state)
st.write("QUEUE=" + "|".join(st.session_state.get("draft_queue") or []))
'''


def _buttons(at: AppTest) -> list[str]:
    return [b.label for b in at.button]


def _click(at: AppTest, label: str, nth: int = 0) -> None:
    [b for b in at.button if b.label == label][nth].click()
    at.run()


def _queue(at: AppTest) -> list[str]:
    text = [m.value for m in at.markdown if str(m.value).startswith("QUEUE=")][-1]
    return [p for p in text[len("QUEUE="):].split("|") if p]


class DraftStrategyPageTests(unittest.TestCase):
    def setUp(self) -> None:
        import ui_confirm

        ui_confirm._PENDING.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "draft_strategies.json"
        self._patch = mock.patch("draft_strategy_store._LocalBackend._path", lambda _self: self.path)
        self._patch.start()
        self._cloud = mock.patch("suite_storage_config.cloud_storage_enabled", return_value=False)
        self._cloud.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._cloud.stop()
        self._tmp.cleanup()

    def _app(self, queue: list[str]) -> AppTest:
        at = AppTest.from_string(SCRIPT, default_timeout=60)
        at.session_state["_seed_queue"] = queue
        at.run()
        return at

    def test_save_then_load_into_an_empty_queue(self) -> None:
        at = self._app(["Aaron Judge", "Juan Soto", "Bobby Witt"])
        self.assertIn("PRO", " ".join(str(c.value) for c in at.caption))
        at.text_input(key="draft_strategy_new_name").input("Points plan")
        _click(at, "Save strategy")
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual([s["name"] for s in saved.values()], ["Points plan"])
        self.assertEqual([p["name"] for p in next(iter(saved.values()))["players"]],
                         ["Aaron Judge", "Juan Soto", "Bobby Witt"])
        # A fresh session with an empty queue loads it without a prompt.
        other = self._app([])
        _click(other, "Load into queue")
        self.assertEqual(_queue(other), ["Aaron Judge", "Juan Soto", "Bobby Witt"])

    def test_loading_over_a_queue_asks_first_and_replaces_it(self) -> None:
        at = self._app(["Aaron Judge"])
        at.text_input(key="draft_strategy_new_name").input("One")
        _click(at, "Save strategy")
        at.session_state["draft_queue"] = ["Shohei Ohtani", "Mookie Betts"]
        at.run()
        _click(at, "Load into queue")
        self.assertIn("Replace queue", _buttons(at))
        self.assertEqual(_queue(at), ["Shohei Ohtani", "Mookie Betts"])  # nothing changed yet
        _click(at, "Replace queue")
        self.assertEqual(_queue(at), ["Aaron Judge"])

    def test_update_and_delete_need_confirmation(self) -> None:
        at = self._app(["Aaron Judge"])
        at.text_input(key="draft_strategy_new_name").input("Plan")
        _click(at, "Save strategy")
        at.session_state["draft_queue"] = ["Juan Soto", "Bobby Witt"]
        at.run()
        _click(at, "Update from queue")
        _click(at, "Update strategy")
        saved = next(iter(json.loads(self.path.read_text(encoding="utf-8")).values()))
        self.assertEqual([p["name"] for p in saved["players"]], ["Juan Soto", "Bobby Witt"])
        delete_btn = next(b for b in at.button if b.label == "Delete strategy")
        self.assertTrue(delete_btn.disabled)  # Slice 0: deletion is paused (strategy_deletion_guard)
        with mock.patch("strategy_deletion_guard.DELETION_PAUSED", False):  # the confirm-then-delete flow, for when Slice 2 lifts the pause
            at.run()
            _click(at, "Delete strategy")
            self.assertTrue(self.path.read_text(encoding="utf-8").count("Plan"))  # still there until confirmed
            _click(at, "Delete")
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {})

    def test_duplicate_and_rename(self) -> None:
        at = self._app(["Aaron Judge"])
        at.text_input(key="draft_strategy_new_name").input("Plan")
        _click(at, "Save strategy")
        _click(at, "Duplicate")
        names = sorted(s["name"] for s in json.loads(self.path.read_text(encoding="utf-8")).values())
        self.assertEqual(names, ["Plan", "Plan (copy)"])

    def test_without_access_the_library_is_explained_not_shown(self) -> None:
        with mock.patch("baseball_monetization.entitlement_for_capability", return_value=False):
            at = self._app(["Aaron Judge"])
            self.assertNotIn("Save strategy", _buttons(at))
            self.assertIn("View Pricing & Upgrade", _buttons(at))
            self.assertTrue(any("Pro feature" in str(i.value) for i in at.info))
            self.assertEqual(_queue(at), ["Aaron Judge"])  # the working queue still shows


if __name__ == "__main__":
    unittest.main()


PLAN_SCRIPT = '''
import pandas as pd
import streamlit as st
from draft_strategy_ui import render_draft_strategy_page

POOL = pd.DataFrame([
    {"fullName": "Aaron Judge", "Primary Position": "OF", "Decision Score": 0.95, "ADP": 2, "proj_HR": 45},
    {"fullName": "Bobby Witt", "Primary Position": "SS", "Decision Score": 0.93, "ADP": 3, "proj_SB": 35},
    {"fullName": "Juan Soto", "Primary Position": "OF", "Decision Score": 0.90, "ADP": 5, "proj_HR": 36},
    {"fullName": "Kyle Tucker", "Primary Position": "OF", "Decision Score": 0.85, "ADP": 9, "proj_HR": 30},
])
if "draft_queue" not in st.session_state:
    st.session_state["draft_queue"] = list(st.session_state.get("_seed_queue") or [])
render_draft_strategy_page(st, st.session_state, pool_fn=lambda: POOL)
st.write("QUEUE=" + "|".join(st.session_state.get("draft_queue") or []))
'''


class StrategyQueueAndPlanTests(DraftStrategyPageTests):
    """Working-queue controls, the loaded-strategy indicator and adding recommended targets."""

    def _plan_app(self, queue: list[str]) -> AppTest:
        at = AppTest.from_string(PLAN_SCRIPT, default_timeout=60)
        at.session_state["_seed_queue"] = queue
        at.run()
        return at

    def _icon_click(self, at: AppTest, key: str) -> None:
        at.button(key=key).click()
        at.run()

    def test_reorder_move_to_top_and_remove(self) -> None:
        at = self._plan_app(["Aaron Judge", "Juan Soto", "Bobby Witt"])
        self._icon_click(at, "dsq_down_0_btn")
        self.assertEqual(_queue(at), ["Juan Soto", "Aaron Judge", "Bobby Witt"])
        self._icon_click(at, "dsq_top_2_btn")
        self.assertEqual(_queue(at), ["Bobby Witt", "Juan Soto", "Aaron Judge"])
        self._icon_click(at, "dsq_rm_1_btn")
        self.assertEqual(_queue(at), ["Bobby Witt", "Aaron Judge"])
        self.assertTrue(at.button(key="dsq_up_0_btn").disabled)

    def test_recommended_targets_are_added_only_when_chosen(self) -> None:
        at = self._plan_app(["Aaron Judge"])
        self.assertEqual(_queue(at), ["Aaron Judge"])                       # nothing added by itself
        labels = " ".join(str(m.value) for m in at.markdown)
        self.assertIn("Bobby Witt", labels)
        self.assertNotIn("1. Aaron Judge** · OF · ADP", labels)            # queued players are not re-recommended
        self._icon_click(at, "dsq_add_Bobby Witt_btn")
        self.assertEqual(_queue(at), ["Aaron Judge", "Bobby Witt"])

    def test_loaded_strategy_indicator_and_independent_snapshots(self) -> None:
        at = self._plan_app(["Aaron Judge", "Juan Soto"])
        at.text_input(key="draft_strategy_new_name").input("Power")
        _click(at, "Save strategy")
        at.session_state["draft_queue"] = ["Bobby Witt"]
        at.run()
        at.text_input(key="draft_strategy_new_name").input("Speed")
        _click(at, "Save strategy")
        saved = {s["name"]: [p["name"] for p in s["players"]] for s in json.loads(self.path.read_text(encoding="utf-8")).values()}
        self.assertEqual(saved, {"Power": ["Aaron Judge", "Juan Soto"], "Speed": ["Bobby Witt"]})
        power_id = [sid for sid, s in json.loads(self.path.read_text(encoding="utf-8")).items() if s["name"] == "Power"][0]
        self._icon_click(at, f"strategy_{power_id}_load_btn__ask_btn")
        _click(at, "Replace queue")
        self.assertEqual(_queue(at), ["Aaron Judge", "Juan Soto"])
        captions = " ".join(str(c.value) for c in at.caption)
        self.assertIn("Loaded from **Power** · unchanged", captions)
        self._icon_click(at, "dsq_rm_0_btn")                                 # edit the working queue
        captions = " ".join(str(c.value) for c in at.caption)
        self.assertIn("edited since loading (the saved strategy is unchanged)", captions)
        saved = {s["name"]: [p["name"] for p in s["players"]] for s in json.loads(self.path.read_text(encoding="utf-8")).values()}
        self.assertEqual(saved, {"Power": ["Aaron Judge", "Juan Soto"], "Speed": ["Bobby Witt"]})  # snapshots intact
