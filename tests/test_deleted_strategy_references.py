"""KI-1 (owner, 2026-11-08): a deleted strategy must stop acting as an active source.

The Global Queue remembers the strategy it was loaded from (session ``_draft_strategy_loaded``: id,
name, notes, queue). Before this fix, deleting that strategy left the record in place, so its notes
still fed Adaptive explanations, were copied into a new strategy made from the Global Queue, and
"Loaded from <name>" stayed under the Global Queue.

Now:
* every delete path drops the record and marks the workspace for the end-of-run save;
* pages, the Adaptive panel and new strategies first check that the strategy is still live, which
  covers deletions on another device;
* the deleted strategy keeps its own notes, pins and research in Recently deleted, and Restore brings
  them back without touching any other strategy;
* the Global Queue's players, order and its own notes are never changed;
* a transient failure (no access, storage unreachable) never erases the record.
"""

from __future__ import annotations

import copy
import unittest
from unittest import mock

import draft_plan_source as dps
import draft_queue_modes as dqm
import draft_queue_panel as panel
import draft_strategy_store as dss
import draft_strategy_ui as dsu
import draft_strategy_v2 as v2
import draft_strategy_work as work
from draft_state import DRAFT_QUEUE_KEY

T0 = "2026-11-01T10:00:00+00:00"


def _strategy(sid: str, name: str, players: list[tuple[str, str]]) -> dict:
    s = v2.new_strategy(name, queue=[{"name": n, "player_id": f"{sid}{i}", "position": "OF"}
                                     for i, (n, _note) in enumerate(players, start=1)])
    s = {**s, "id": sid, "created_at": T0, "updated_at": T0}
    for n, note in players:
        if note:
            s = v2.set_note(s, n, note)
    return v2.pin(s, players[0][0])


class _Backend:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.fail = False

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("offline")

    def put(self, key, title, payload):
        self._check()
        self.rows[key] = copy.deepcopy(payload)

    def all(self):
        self._check()
        return copy.deepcopy(list(self.rows.values()))

    def fetch(self, key):
        self._check()
        return copy.deepcopy(self.rows.get(key))

    def delete(self, key):
        self._check()
        self.rows.pop(key, None)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.backends = {t: _Backend() for t in (v2.ITEM_TYPE, v2.BACKUP_ITEM_TYPE, v2.RESEARCH_ITEM_TYPE,
                                                 v2.TRASH_ITEM_TYPE)}
        for p in (mock.patch("draft_strategy_store._backend", side_effect=lambda t=v2.ITEM_TYPE: self.backends[t]),
                  mock.patch("suite_auth.is_auth_enabled", return_value=False)):
            p.start()
            self.addCleanup(p.stop)
        self.rows = self.backends[v2.ITEM_TYPE].rows
        self.rows["P"] = _strategy("P", "Power", [("Aaron Judge", "elite power"), ("Kyle Schwarber", "")])
        self.rows["S"] = _strategy("S", "Speed", [("Elly De La Cruz", "steals"), ("Bobby Witt Jr.", "five tools")])
        v2.append_research({}, "P", "Judge's barrel rate leads the board", kind="finding", player="Aaron Judge")
        self.s: dict = {}
        work.open_strategy(self.s, "P")
        work.replace_global_with(self.s, "P", confirmed=True)  # Global Queue loaded from Power
        # The Global Queue's own note, independent of any strategy.
        dqm.set_note(self.s, "Kyle Schwarber", "own note: platoon risk")
        self.s.pop(dqm.SAVE_PENDING_KEY, None)
        self.queue_before = list(self.s[DRAFT_QUEUE_KEY])

    def assertGlobalQueueKept(self) -> None:
        self.assertEqual(self.s[DRAFT_QUEUE_KEY], self.queue_before)
        self.assertEqual(dqm.plan(self.s)["notes"].get("kyle schwarber"), "own note: platoon risk")

    def assertNoLongerActive(self) -> None:
        self.assertNotIn(dss.LOADED_KEY, self.s)
        self.assertIsNone(dsu.loaded_strategy_state(self.s, self.s[DRAFT_QUEUE_KEY]))  # no "Loaded from"
        self.assertNotIn("aaron judge", dqm.notes_for(self.s))  # Adaptive stops using its notes
        self.assertEqual(dqm.notes_for(self.s).get("kyle schwarber"), "own note: platoon risk")


class SetupSanityTests(_Base):
    def test_the_global_queue_starts_loaded_from_power(self) -> None:
        self.assertEqual(self.s[dss.LOADED_KEY]["id"], "P")
        self.assertEqual(dqm.notes_for(self.s).get("aaron judge"), "elite power")
        self.assertTrue(dsu.loaded_strategy_state(self.s, self.s[DRAFT_QUEUE_KEY]))


class DeletePathTests(_Base):
    def test_store_delete_drops_the_record_and_marks_a_save(self) -> None:
        dss.delete_strategy(self.s, "P", confirmed=True)
        self.assertNoLongerActive()
        self.assertTrue(self.s.get(dqm.SAVE_PENDING_KEY))  # saved at the end of the run
        self.assertGlobalQueueKept()

    def test_pro_editor_delete_path(self) -> None:
        v2.soft_delete(self.s, "P", confirmed=True)
        self.assertTrue(dss.forget_loaded(self.s, "P"))
        self.assertNoLongerActive()
        self.assertGlobalQueueKept()

    def test_deleting_a_different_strategy_keeps_the_record(self) -> None:
        dss.delete_strategy(self.s, "S", confirmed=True)
        self.assertEqual(self.s[dss.LOADED_KEY]["id"], "P")
        self.assertFalse(dss.forget_loaded(self.s, "S"))
        self.assertEqual(dqm.notes_for(self.s).get("aaron judge"), "elite power")

    def test_deleted_on_another_device_is_caught_by_the_live_check(self) -> None:
        other_device: dict = {}
        v2.soft_delete(other_device, "P", confirmed=True)  # this session still holds the record
        self.assertIn(dss.LOADED_KEY, self.s)
        dss.reconcile_loaded_strategy(self.s)
        self.assertNoLongerActive()
        self.assertGlobalQueueKept()

    def test_the_adaptive_panel_checks_before_building_explanations(self) -> None:
        self.rows.pop("P")  # gone (purged elsewhere)
        live = panel._live_strategy_ids(self.s)
        self.assertEqual(live, {"S"})
        self.assertNoLongerActive()
        self.assertTrue(panel._deleted_since(live, "P"))
        self.assertFalse(panel._deleted_since(live, "S"))
        self.assertFalse(panel._deleted_since(None, "P"))  # unknown is never shown as deleted

    def test_an_explanation_no_longer_quotes_the_deleted_note(self) -> None:
        dss.delete_strategy(self.s, "P", confirmed=True)
        event = dqm.explain_move("Aaron Judge", 5, 1, 1, {}, "balanced", {}, {}, self.s, [])
        self.assertNotIn("elite power", " ".join(event.get("reasons") or []))

    def test_permanent_delete_of_a_restore_original_copy_keeps_a_live_record(self) -> None:
        # A row kept before Restore Original shares its id with the live strategy.
        v2._to_trash(self.rows["P"], reason="before_restore_original", at="2026-11-08T12:00:00+00:00")
        tid = v2.list_trash(self.s)[0]["trash_id"]
        v2.permanent_delete(self.s, tid, confirmed=True)
        dss.reconcile_loaded_strategy(self.s)
        self.assertEqual(self.s[dss.LOADED_KEY]["id"], "P")


class NewStrategyTests(_Base):
    def test_a_new_strategy_from_the_global_queue_does_not_inherit_deleted_notes(self) -> None:
        other_device: dict = {}
        v2.soft_delete(other_device, "P", confirmed=True)
        rec = work.create(self.s, "Fresh", from_global=True)
        notes = rec["strategy"]["notes"]
        self.assertNotIn("aaron judge", notes)
        self.assertEqual(notes["kyle schwarber"]["text"], "own note: platoon risk")  # the queue's own note
        self.assertEqual([e["name"] for e in rec["strategy"]["queue"]], self.queue_before)

    def test_a_live_loaded_strategy_still_contributes_its_notes(self) -> None:
        rec = work.create(self.s, "Copy", from_global=True)
        self.assertEqual(rec["strategy"]["notes"]["aaron judge"]["text"], "elite power")


class RecoveryTests(_Base):
    def test_notes_pins_and_research_stay_recoverable_and_restore_touches_nothing_else(self) -> None:
        speed_before = copy.deepcopy(self.rows["S"])
        dss.delete_strategy(self.s, "P", confirmed=True)
        row = v2.list_trash(self.s)[0]
        self.assertEqual(row["strategy"]["notes"]["aaron judge"]["text"], "elite power")
        self.assertEqual(row["strategy"]["pins"], ["aaron judge"])
        self.assertEqual(len(self.backends[v2.RESEARCH_ITEM_TYPE].rows["P"]["entries"]), 1)  # kept while deleted
        restored = v2.restore_from_trash(self.s, row["trash_id"])
        self.assertEqual(restored["id"], "P")
        self.assertEqual(v2.get_strategy_v2(self.s, "P")["notes"]["aaron judge"]["text"], "elite power")
        self.assertEqual(v2.get_strategy_v2(self.s, "P")["pins"], ["aaron judge"])
        self.assertEqual([e["text"] for e in v2.research_log(self.s, "P")], ["Judge's barrel rate leads the board"])
        self.assertEqual(self.rows["S"], speed_before)
        # Restoring does not silently make it the Global Queue's source again.
        self.assertNotIn(dss.LOADED_KEY, self.s)
        self.assertGlobalQueueKept()

    def test_a_draft_cannot_save_back_to_a_deleted_strategy(self) -> None:
        source = "sim:1"
        self.s.setdefault("draft_queue_adaptive", {})[source] = {}  # the draft is open
        dps.choose(self.s, source, "P")
        self.assertEqual(dps.current(self.s, source)["id"], "P")
        dss.delete_strategy(self.s, "P", confirmed=True)
        with self.assertRaises(dss.StrategyError) as caught:
            dps.save_back(self.s, source, confirmed=True)
        self.assertIn("no longer exists", str(caught.exception))
        self.assertNotIn("P", self.rows)
        self.assertIsNotNone(dps.current(self.s, source))  # the draft keeps its own copy


class NoFalseDropTests(_Base):
    def test_a_live_strategy_keeps_its_record(self) -> None:
        self.assertEqual(dss.active_loaded_record(self.s)["id"], "P")
        self.assertFalse(self.s.get(dqm.SAVE_PENDING_KEY))

    def test_storage_unreachable_keeps_the_record(self) -> None:
        self.backends[v2.ITEM_TYPE].fail = True
        self.assertIsNone(dss.active_loaded_record(self.s))  # not presented as active this run
        self.assertEqual(self.s[dss.LOADED_KEY]["id"], "P")  # but never erased
        self.backends[v2.ITEM_TYPE].fail = False
        self.assertEqual(dss.active_loaded_record(self.s)["id"], "P")

    def test_no_access_keeps_the_record(self) -> None:
        with mock.patch("draft_strategy_store._require_access", side_effect=dss.StrategyError("Sign in")):
            self.assertIsNone(dss.active_loaded_record(self.s))
        self.assertEqual(self.s[dss.LOADED_KEY]["id"], "P")

    def test_a_malformed_record_is_dropped(self) -> None:
        self.s[dss.LOADED_KEY] = {"name": "no id"}
        self.assertIsNone(dss.active_loaded_record(self.s))
        self.assertNotIn(dss.LOADED_KEY, self.s)

    def test_reconcile_never_raises(self) -> None:
        with mock.patch("draft_strategy_store.active_loaded_record", side_effect=RuntimeError("boom")):
            dss.reconcile_loaded_strategy(self.s)


if __name__ == "__main__":
    unittest.main()
