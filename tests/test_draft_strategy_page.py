"""Draft Strategy Assistant page through the real widgets: the Global Queue (free) and, since S2,
Pro Draft Strategies edited as working copies (draft_strategy_pro_ui / draft_strategy_work).

The stores are tested on their own; this drives the page with AppTest and a temporary strategy
file, so no workspace or account data is touched.
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
    # A handler that calls st.rerun() mid-run leaves that run's elements in AppTest's tree until the
    # next plain run (a browser drops them); without this a later click can hit the stale copy.
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

    def _stored(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def _trash(self) -> dict:
        path = self.path.with_name("draft_strategy_trash.json")
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _create(self, at: AppTest, name: str, *, from_global: bool = True) -> str:
        at.text_input(key="draft_strategy_new_name").input(name)
        at.radio(key="draft_strategy_new_from").set_value("global" if from_global else "empty")
        _click(at, "Create strategy")
        return next(sid for sid, s in self._stored().items() if s["name"] == name)

    def _queue_of(self, sid: str) -> list[str]:
        return [e["name"] for e in self._stored()[sid]["queue"]]

    def _unsaved(self, at: AppTest) -> bool:
        return any("Unsaved changes" in str(w.value) for w in at.warning)

    def test_create_from_the_global_queue_then_edit_only_the_strategy(self) -> None:
        at = self._app(["Aaron Judge", "Juan Soto", "Bobby Witt"])
        self.assertIn("PRO", " ".join(str(c.value) for c in at.caption))
        sid = self._create(at, "Points plan")
        self.assertEqual(self._queue_of(sid), ["Aaron Judge", "Juan Soto", "Bobby Witt"])
        at.button(key=f"dsp_{sid}_down_0").click().run()
        self.assertTrue(self._unsaved(at))
        self.assertEqual(self._queue_of(sid), ["Aaron Judge", "Juan Soto", "Bobby Witt"])  # not saved yet
        _click(at, "Save strategy")
        self.assertEqual(self._queue_of(sid), ["Juan Soto", "Aaron Judge", "Bobby Witt"])
        self.assertFalse(self._unsaved(at))
        self.assertEqual(_queue(at), ["Aaron Judge", "Juan Soto", "Bobby Witt"])  # the Global Queue never moved

    def test_switching_strategies_keeps_unsaved_changes(self) -> None:
        at = self._app(["Aaron Judge", "Juan Soto"])
        a = self._create(at, "Alpha")
        b = self._create(at, "Bravo")
        at.selectbox(key="_draft_strategy_open_pick").set_value(a).run()
        at.button(key=f"dsp_{a}_rm_0").click().run()
        at.selectbox(key="_draft_strategy_open_pick").set_value(b).run()
        self.assertFalse(self._unsaved(at))  # Bravo is clean
        self.assertTrue(any("Unsaved changes also in: Alpha" in str(c.value) for c in at.caption))
        at.selectbox(key="_draft_strategy_open_pick").set_value(a).run()
        self.assertTrue(self._unsaved(at))
        self.assertEqual(self._queue_of(a), ["Aaron Judge", "Juan Soto"])  # only in the working copy
        self.assertEqual(self._queue_of(b), ["Aaron Judge", "Juan Soto"])
        _click(at, "Discard changes")
        self.assertFalse(self._unsaved(at))
        self.assertEqual(_queue(at), ["Aaron Judge", "Juan Soto"])

    def test_replace_global_queue_with_this_strategy_asks_first_and_shows_counts(self) -> None:
        at = self._app(["Aaron Judge", "Juan Soto"])
        sid = self._create(at, "Power")
        at.session_state["draft_queue"] = ["Shohei Ohtani"]
        at.run()
        text = " ".join(str(m.value) for m in at.markdown)
        self.assertIn("From **Power** (2 players) → **Global Queue** (1 player now)", text)
        self.assertIn("2 players added · 1 player removed · 0 kept", text)
        at.button(key=f"dsp_{sid}_replace_global__ask_btn").click().run()
        self.assertEqual(_queue(at), ["Shohei Ohtani"])  # nothing changed yet
        _click(at, "Replace Global Queue")
        self.assertEqual(_queue(at), ["Aaron Judge", "Juan Soto"])
        self.assertEqual(self._queue_of(sid), ["Aaron Judge", "Juan Soto"])  # the strategy is unchanged

    def test_copy_global_queue_into_an_empty_strategy_then_save(self) -> None:
        at = self._app(["Aaron Judge", "Juan Soto"])
        sid = self._create(at, "Blank", from_global=False)
        self.assertEqual(self._queue_of(sid), [])
        _click(at, "Copy Global Queue into This Strategy")  # nothing to replace: no prompt
        self.assertEqual(self._queue_of(sid), [])           # a working copy until saved
        _click(at, "Save strategy")
        self.assertEqual(self._queue_of(sid), ["Aaron Judge", "Juan Soto"])
        self.assertEqual(_queue(at), ["Aaron Judge", "Juan Soto"])

    def test_copy_over_existing_players_needs_confirmation(self) -> None:
        at = self._app(["Aaron Judge"])
        sid = self._create(at, "Plan")
        at.session_state["draft_queue"] = ["Juan Soto", "Bobby Witt"]
        at.run()
        at.button(key=f"dsp_{sid}_copy_global__ask_btn").click().run()
        self.assertEqual(self._queue_of(sid), ["Aaron Judge"])
        _click(at, "Copy into strategy")
        _click(at, "Save strategy")
        self.assertEqual(self._queue_of(sid), ["Juan Soto", "Bobby Witt"])
        self.assertEqual(_queue(at), ["Juan Soto", "Bobby Witt"])

    def test_delete_is_recoverable_and_permanent_delete_is_confirmed(self) -> None:
        at = self._app(["Aaron Judge"])
        sid = self._create(at, "Plan")
        at.button(key=f"dsp_{sid}_delete__ask_btn").click().run()
        self.assertIn(sid, self._stored())  # still there until confirmed
        _click(at, "Delete")
        self.assertNotIn(sid, self._stored())
        self.assertEqual(len(self._trash()), 1)
        _click(at, "Restore")
        self.assertIn(sid, self._stored())
        self.assertEqual(self._trash(), {})
        at.button(key=f"dsp_{sid}_delete__ask_btn").click().run()
        _click(at, "Delete")
        (tid,) = self._trash()
        at.button(key=f"dsp_trash_{tid}_purge__ask_btn").click().run()
        self.assertEqual(len(self._trash()), 1)  # still recoverable until confirmed
        _click(at, "Delete forever")
        self.assertEqual(self._trash(), {})
        self.assertEqual(self._stored(), {})

    def test_duplicate(self) -> None:
        at = self._app(["Aaron Judge"])
        self._create(at, "Plan")
        _click(at, "Duplicate")
        self.assertEqual(sorted(s["name"] for s in self._stored().values()), ["Plan", "Plan (copy)"])

    def test_without_access_the_library_is_explained_not_shown(self) -> None:
        with mock.patch("baseball_monetization.entitlement_for_capability", return_value=False):
            at = self._app(["Aaron Judge"])
            self.assertNotIn("Create strategy", _buttons(at))
            self.assertIn("View Pricing & Upgrade", _buttons(at))
            self.assertTrue(any("Pro feature" in str(i.value) for i in at.info))
            self.assertEqual(_queue(at), ["Aaron Judge"])  # the Global Queue still shows


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
    """Global Queue controls, the loaded-strategy indicator and adding players from the pool."""

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

    def test_add_a_pool_player_and_pin_in_a_strategy_only(self) -> None:
        at = self._plan_app(["Aaron Judge"])
        sid = self._create(at, "Power")
        at.selectbox(key=f"dsp_{sid}_add_pick").set_value("Kyle Tucker").run()
        _click(at, "Add to this strategy")
        at.button(key=f"dsp_{sid}_pin_1").click().run()
        _click(at, "Save strategy")
        stored = self._stored()[sid]
        self.assertEqual([e["name"] for e in stored["queue"]], ["Aaron Judge", "Kyle Tucker"])
        self.assertEqual(stored["queue"][1]["position"], "OF")
        self.assertEqual(stored["pins"], ["kyle tucker"])
        self.assertEqual(stored["queue"][0]["mlbam_id"], "592450")  # resolved offline (seed map)
        self.assertEqual(_queue(at), ["Aaron Judge"])

    def test_note_preferences_and_research_are_saved_with_the_strategy(self) -> None:
        at = self._plan_app(["Aaron Judge", "Juan Soto"])
        sid = self._create(at, "Power")
        at.selectbox(key=f"dsp_{sid}_note_who").set_value("Juan Soto").run()
        at.text_area(key=f"dsp_{sid}_note_text_juan soto").input("Elite plate discipline").run()
        _click(at, "Save note")
        at.selectbox(key=f"dsp_{sid}_approach").set_value("roster_aware").run()
        at.multiselect(key=f"dsp_{sid}_cats").set_value(["HR", "RBI"]).run()
        _click(at, "Apply preferences")
        _click(at, "Save strategy")
        stored = self._stored()[sid]
        self.assertEqual(stored["notes"]["juan soto"]["text"], "Elite plate discipline")
        self.assertEqual(stored["notes"]["juan soto"]["mlbam_id"], "665742")
        self.assertEqual(stored["approach"], "roster_aware")
        self.assertEqual(stored["preferences"]["category_priorities"], ["HR", "RBI"])
        at.text_area(key=f"dsp_{sid}_finding").input("Judge vs Soto: Judge has more HR over 5 seasons.").run()
        _click(at, "Add finding")
        log = json.loads(self.path.with_name("draft_strategy_research.json").read_text(encoding="utf-8"))
        self.assertEqual(log[sid]["entries"][0]["kind"], "finding")

    def test_loaded_strategy_indicator_and_independent_strategies(self) -> None:
        at = self._plan_app(["Aaron Judge", "Juan Soto"])
        power = self._create(at, "Power")
        at.session_state["draft_queue"] = ["Bobby Witt"]
        at.run()
        self._create(at, "Speed")
        names = {s["name"]: [e["name"] for e in s["queue"]] for s in self._stored().values()}
        self.assertEqual(names, {"Power": ["Aaron Judge", "Juan Soto"], "Speed": ["Bobby Witt"]})
        at.selectbox(key="_draft_strategy_open_pick").set_value(power).run()
        at.button(key=f"dsp_{power}_replace_global__ask_btn").click().run()
        _click(at, "Replace Global Queue")
        self.assertEqual(_queue(at), ["Aaron Judge", "Juan Soto"])
        captions = " ".join(str(c.value) for c in at.caption)
        self.assertIn("Loaded from **Power** · unchanged", captions)
        self._icon_click(at, "dsq_rm_0_btn")                                 # edit the Global Queue
        captions = " ".join(str(c.value) for c in at.caption)
        self.assertIn("edited since loading (the saved strategy is unchanged)", captions)
        names = {s["name"]: [e["name"] for e in s["queue"]] for s in self._stored().values()}
        self.assertEqual(names, {"Power": ["Aaron Judge", "Juan Soto"], "Speed": ["Bobby Witt"]})


if __name__ == "__main__":
    unittest.main()
