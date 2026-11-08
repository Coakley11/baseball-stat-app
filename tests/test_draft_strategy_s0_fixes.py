"""Pro Draft Strategy S0 (2026-11-08): reader tolerance and saved-strategy bug fixes.

- The reader lists any ``schema_version >= 1`` row, so a rollback still reads upgraded rows.
- The loaded-strategy record keeps its notes and approach (the page used to overwrite it) and
  records the queue as loaded (the panel's load never did, so the page always said "edited").
- Saving from the page passes the user's queue notes, so notes survive save -> load.
- Help text no longer says drafting takes players off the queue.
"""

from __future__ import annotations

import contextlib
import unittest
from unittest import mock

import draft_queue_modes as dqm
import draft_strategy_store as dss
import draft_strategy_ui as dsu
from draft_state import DRAFT_QUEUE_KEY

QUEUE = ["Aaron Judge", "Juan Soto", "Bobby Witt"]


class _MemoryBackend:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def put(self, key, title, payload):
        self.rows[key] = payload

    def all(self):
        return list(self.rows.values())

    def delete(self, key):
        self.rows.pop(key, None)


class _FakeSt:
    """Just enough of Streamlit for _render_save / _render_strategy's update branch."""

    def __init__(self, name: str = "", click: str = "") -> None:
        self.session_state: dict = {}
        self._name, self._click = name, click

    def container(self, **_kw):
        return contextlib.nullcontext()

    def markdown(self, *_a, **_kw):
        return None

    caption = markdown

    def text_input(self, *_a, **_kw):
        return self._name

    def button(self, label, *_a, **_kw):
        return label == self._click

    def rerun(self):
        return None


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = _MemoryBackend()
        for p in (mock.patch("draft_strategy_store._backend", return_value=self.backend),
                  mock.patch("suite_auth.is_auth_enabled", return_value=False),
                  mock.patch("draft_strategy_ui._persist"),
                  mock.patch("draft_strategy_ui._flash"),
                  mock.patch("draft_queue_modes.mark_personal_change")):
            p.start()
            self.addCleanup(p.stop)
        self.s = {DRAFT_QUEUE_KEY: list(QUEUE)}


class ReaderTests(_Base):
    def test_reader_lists_v1_and_later_versions_only(self) -> None:
        base = {"name": "x", "players": [], "updated_at": "2026-11-01"}
        self.backend.rows = {
            "a": {**base, "id": "a", "name": "A", "schema_version": 1},
            "b": {**base, "id": "b", "name": "B", "schema_version": 2, "revision": 3},
            "c": {**base, "id": "c", "name": "C", "schema_version": "3"},
            "d": {**base, "id": "d", "name": "D"},
            "e": {**base, "id": "e", "name": "E", "schema_version": 0},
            "f": {**base, "id": "f", "name": "F", "schema_version": "garbage"},
            "g": {**base, "name": "G", "schema_version": 2},  # no id
        }
        self.assertEqual(sorted(s["id"] for s in dss.list_strategies(self.s)), ["a", "b", "c"])

    def test_a_v2_row_loads_through_its_v1_mirror(self) -> None:
        self.backend.rows["b"] = {
            "schema_version": 2, "revision": 4, "id": "b", "name": "Upgraded", "approach": "value_based",
            "updated_at": "2026-11-01",
            "players": [{"rank": 2, "name": "Juan Soto", "player_id": "", "position": "OF", "note": ""},
                        {"rank": 1, "name": "Aaron Judge", "player_id": "592450", "position": "OF", "note": "power"}],
        }
        self.s[DRAFT_QUEUE_KEY] = []
        dss.load_strategy(self.s, "b")
        self.assertEqual(self.s[DRAFT_QUEUE_KEY], ["Aaron Judge", "Juan Soto"])
        self.assertEqual(self.s[dss.LOADED_KEY]["notes"], {"Aaron Judge": "power"})


class LoadedRecordTests(_Base):
    def _saved(self) -> dict:
        return dss.save_strategy(self.s, "Power", approach="roster_aware", notes={"aaron judge": "elite power"})

    def test_store_load_records_queue_notes_and_approach(self) -> None:
        strategy = self._saved()
        self.s[DRAFT_QUEUE_KEY] = []
        dss.load_strategy(self.s, strategy["id"])
        loaded = self.s[dss.LOADED_KEY]
        self.assertEqual(loaded["queue"], QUEUE)
        self.assertEqual(loaded["notes"], {"Aaron Judge": "elite power"})
        self.assertEqual(loaded["approach"], "roster_aware")
        self.assertFalse(dsu.loaded_strategy_state(self.s, self.s[DRAFT_QUEUE_KEY])["modified"])
        self.assertTrue(dsu.loaded_strategy_state(self.s, QUEUE[:2])["modified"])

    def test_page_load_keeps_the_store_record(self) -> None:
        strategy = self._saved()
        self.s[DRAFT_QUEUE_KEY] = ["Someone Else"]
        dsu._load(_FakeSt(), self.s, strategy["id"])
        loaded = self.s[dss.LOADED_KEY]
        self.assertEqual(self.s[DRAFT_QUEUE_KEY], QUEUE)
        self.assertEqual(loaded["notes"], {"Aaron Judge": "elite power"})  # used to be dropped
        self.assertEqual(loaded["approach"], "roster_aware")
        self.assertEqual(loaded["name"], "Power")
        self.assertFalse(dsu.loaded_strategy_state(self.s, self.s[DRAFT_QUEUE_KEY])["modified"])
        self.assertEqual(dqm.notes_for(self.s).get("aaron judge"), "elite power")

    def test_panel_load_is_not_reported_as_edited(self) -> None:
        from draft_queue_panel import _load_plan

        strategy = self._saved()
        self.s[DRAFT_QUEUE_KEY] = ["Someone Else"]
        _load_plan(self.s, strategy, "_flash")
        self.assertEqual(self.s["_flash"]["kind"], "success")
        state = dsu.loaded_strategy_state(self.s, self.s[DRAFT_QUEUE_KEY])
        self.assertFalse(state["modified"])  # used to always say "edited since loading"
        self.assertEqual(state["notes"], {"Aaron Judge": "elite power"})


class NotesRoundTripTests(_Base):
    def test_page_save_keeps_queue_notes_through_load(self) -> None:
        dqm.set_note(self.s, "Juan Soto", "walks a ton")
        dsu._render_save(_FakeSt(name="Patience", click="Save strategy"), self.s, QUEUE)
        (saved,) = self.backend.rows.values()
        self.assertEqual({p["name"]: p["note"] for p in saved["players"]},
                         {"Aaron Judge": "", "Juan Soto": "walks a ton", "Bobby Witt": ""})
        fresh = {DRAFT_QUEUE_KEY: []}
        dsu._load(_FakeSt(), fresh, saved["id"])
        self.assertEqual(dqm.notes_for(fresh), {"juan soto": "walks a ton"})

    def test_update_from_queue_keeps_old_notes_and_adds_new_ones(self) -> None:
        strategy = dss.save_strategy(self.s, "S", notes={"aaron judge": "elite power"})
        dqm.set_note(self.s, "Bobby Witt", "speed")
        updated = dss.update_strategy(self.s, strategy["id"], confirm_overwrite=True, notes=dqm.notes_for(self.s))
        self.assertEqual({p["name"]: p["note"] for p in updated["players"]},
                         {"Aaron Judge": "elite power", "Juan Soto": "", "Bobby Witt": "speed"})

    def test_update_without_notes_is_unchanged_behaviour(self) -> None:
        strategy = dss.save_strategy(self.s, "S", notes={"aaron judge": "elite power"})
        updated = dss.update_strategy(self.s, strategy["id"], confirm_overwrite=True)
        self.assertEqual(updated["players"][0]["note"], "elite power")


class HelpTextTests(unittest.TestCase):
    def test_help_matches_the_queue_contract(self) -> None:
        from ami_assistant.page_help import PAGE_HELP

        text = " ".join(PAGE_HELP["Draft Strategy Assistant"].reading)
        self.assertNotIn("takes players off", text)
        self.assertIn("stays in your queue", text)


if __name__ == "__main__":
    unittest.main()
