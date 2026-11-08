"""Pro Draft Strategy S2 (2026-11-08): strategies wired into the UI, owner decisions applied.

- Size: up to 300 players; caps refuse growth only, never trim a stored strategy.
- Deletion: recoverable for 30 days (own item type), separately confirmed permanent delete, lazy
  purge on the owner's list, Restore Original Version keeps the current version recoverable.
- Player ids: MLBAM id attached only when it resolves unambiguously offline; notes found by id first.
- Working copies: one strategy's edits never touch another strategy or the Global Queue; the two
  transfers are explicit and confirmed.
- Draft plan: a draft can follow a strategy copy; Fixed/Adaptive use it; masters stay unchanged.
- S0 floor: the S0 reader still lists and loads what S2 writes, and never sees deleted strategies.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import draft_plan_source as dps
import draft_queue_modes as dqm
import draft_strategy_ids as ids
import draft_strategy_store as dss
import draft_strategy_v2 as v2
import draft_strategy_work as work
from draft_state import DRAFT_QUEUE_KEY
from tests.test_draft_strategy_v2 import T0, _Backend, _v1

ROOT = Path(__file__).resolve().parents[1]
TYPES = (v2.ITEM_TYPE, v2.BACKUP_ITEM_TYPE, v2.RESEARCH_ITEM_TYPE, v2.TRASH_ITEM_TYPE)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.backends = {t: _Backend() for t in TYPES}
        for p in (mock.patch("draft_strategy_store._backend", side_effect=lambda t=v2.ITEM_TYPE: self.backends[t]),
                  mock.patch("suite_auth.is_auth_enabled", return_value=False)):
            p.start()
            self.addCleanup(p.stop)
        self.rows = self.backends[v2.ITEM_TYPE].rows
        self.rows["A"] = _v1("A", "Alpha", [("Aaron Judge", "power"), ("Juan Soto", ""), ("Bobby Witt", "")])
        self.rows["B"] = _v1("B", "Bravo", [("Kyle Tucker", "")])
        self.s = {DRAFT_QUEUE_KEY: ["Global One", "Global Two"], "draft_queue_plan": {"pins": [], "notes": {}, "moves": []}}

    def trash(self) -> dict:
        return self.backends[v2.TRASH_ITEM_TYPE].rows


class SizeTests(_Base):
    def test_300_players_fit_and_the_301st_is_refused(self) -> None:
        s = v2.new_strategy("Big", queue=[f"Player {i}" for i in range(300)], at=T0)
        for i in range(0, 300, 3):
            s = v2.set_note(s, f"Player {i}", "n" * v2.NOTE_MAX)
        self.assertLess(v2.encoded_size(s), v2.MAX_BYTES)
        with self.assertRaises(dss.StrategyError) as ctx:
            v2.insert(s, "One More")
        self.assertIn("300", str(ctx.exception))

    def test_a_larger_stored_strategy_is_never_trimmed(self) -> None:
        big = v2.upgrade(_v1("L", "Legacy", [(f"P{i}", "") for i in range(350)]))
        big["notes"] = {"p1": {"text": "x" * 900, "updated_at": T0, "source": "user"}}
        big["pins"] = [f"p{i}" for i in range(40)]
        stored = {**big, "revision": 3}
        self.rows["L"] = stored
        s = v2.get_strategy_v2(self.s, "L")
        self.assertEqual(len(s["queue"]), 350)
        self.assertEqual(len(s["notes"]["p1"]["text"]), 900)
        self.assertEqual(len(s["pins"]), 40)
        with self.assertRaises(dss.StrategyError):
            v2.insert(s, "New Guy")                    # growth past the cap is refused
        moved = v2.move(s, "P349", 0)                  # an edit that does not grow it still works
        saved = v2.save_strategy_v2(self.s, moved, 3)
        self.assertEqual(len(self.rows["L"]["queue"]), 350)
        self.assertEqual(self.rows["L"]["queue"][0]["name"], "P349")
        self.assertEqual(len(self.rows["L"]["notes"]["p1"]["text"]), 900)
        self.assertEqual(saved["revision"], 4)

    @mock.patch.object(v2, "MAX_BYTES", 8 * 1024)
    def test_an_oversized_strategy_may_shrink_but_not_grow(self) -> None:
        s = v2.upgrade(self.rows["A"])
        s = {**s, "context": {"blob": "q" * 9000}}
        self.rows["A"] = {**s, "revision": 1}
        s = v2.get_strategy_v2(self.s, "A")
        v2.save_strategy_v2(self.s, v2.remove(s, "Bobby Witt"), 1)  # smaller: allowed
        with self.assertRaises(dss.StrategyError):
            v2.set_note(v2.get_strategy_v2(self.s, "A"), "Juan Soto", "longer " * 30)


class TrashTests(_Base):
    def test_delete_moves_to_trash_and_hides_the_strategy(self) -> None:
        row = v2.soft_delete(self.s, "A", confirmed=True)
        self.assertNotIn("A", self.rows)
        self.assertEqual([s["id"] for s in dss.list_strategies(self.s)], ["B"])
        (listed,) = v2.list_trash(self.s)
        self.assertEqual((listed["trash_id"], listed["days_left"]), (row["trash_id"], 30))
        restored = v2.restore_from_trash(self.s, row["trash_id"])
        self.assertEqual(restored["id"], "A")
        self.assertEqual(self.rows["A"]["players"], _v1("A", "Alpha", [("Aaron Judge", "power"), ("Juan Soto", ""),
                                                                   ("Bobby Witt", "")])["players"])
        self.assertEqual(self.trash(), {})

    def test_confirmation_is_required(self) -> None:
        with self.assertRaises(dss.StrategyError):
            v2.soft_delete(self.s, "A", confirmed=False)
        row = v2.soft_delete(self.s, "A", confirmed=True)
        with self.assertRaises(dss.StrategyError):
            v2.permanent_delete(self.s, row["trash_id"], confirmed=False)
        self.assertIn(row["trash_id"], self.trash())

    def test_a_stale_copy_cannot_delete_newer_work(self) -> None:
        s = v2.get_strategy_v2(self.s, "A")
        v2.save_strategy_v2(self.s, v2.remove(s, "Juan Soto"), 0)   # another tab saves first
        with self.assertRaises(dss.StrategyError):
            v2.soft_delete(self.s, "A", confirmed=True, base_revision=0, base_updated_at=s["updated_at"])
        self.assertIn("A", self.rows)

    def test_permanent_delete_takes_research_and_backup_with_it(self) -> None:
        v2.save_strategy_v2(self.s, v2.remove(v2.get_strategy_v2(self.s, "A"), "Juan Soto"), 0)  # makes a v1 backup
        v2.append_research(self.s, "A", "Judge hits more HR")
        self.assertIn("A", self.backends[v2.BACKUP_ITEM_TYPE].rows)
        row = v2.soft_delete(self.s, "A", confirmed=True)
        self.assertIn("A", self.backends[v2.RESEARCH_ITEM_TYPE].rows)  # kept while recoverable
        v2.permanent_delete(self.s, row["trash_id"], confirmed=True)
        self.assertEqual(self.trash(), {})
        self.assertNotIn("A", self.backends[v2.RESEARCH_ITEM_TYPE].rows)
        self.assertNotIn("A", self.backends[v2.BACKUP_ITEM_TYPE].rows)
        self.assertIn("B", self.rows)

    def test_items_past_30_days_are_purged_on_the_owners_list(self) -> None:
        v2.append_research(self.s, "B", "speed")
        with mock.patch("draft_strategy_store._now", return_value="2026-10-01T10:00:00+00:00"):
            old = v2.soft_delete(self.s, "B", confirmed=True)
        with mock.patch("draft_strategy_store._now", return_value="2026-11-01T09:00:00+00:00"):
            recent = v2.soft_delete(self.s, "A", confirmed=True)
        listed = v2.list_trash(self.s, now="2026-11-01T10:00:00+00:00")
        self.assertEqual([r["trash_id"] for r in listed], [recent["trash_id"]])
        self.assertNotIn(old["trash_id"], self.trash())
        self.assertNotIn("B", self.backends[v2.RESEARCH_ITEM_TYPE].rows)
        self.assertEqual(listed[0]["days_left"], 30)

    def test_restore_original_keeps_the_current_version_recoverable(self) -> None:
        s = v2.get_strategy_v2(self.s, "A")
        edited = v2.save_strategy_v2(self.s, v2.move(v2.remove(s, "Bobby Witt"), "Juan Soto", 0), 0)
        with self.assertRaises(dss.StrategyError):
            v2.restore_original_version(self.s, "A", confirmed=False)
        with self.assertRaises(dss.StrategyError):  # a stale copy is refused
            v2.restore_original_version(self.s, "A", confirmed=True, base_revision=0)
        out = v2.restore_original_version(self.s, "A", confirmed=True, base_revision=edited["revision"],
                                          base_updated_at=edited["updated_at"])
        self.assertEqual([e["name"] for e in out["queue"]], ["Aaron Judge", "Juan Soto", "Bobby Witt"])
        self.assertEqual(out["revision"], edited["revision"] + 1)
        (kept,) = v2.list_trash(self.s)
        self.assertEqual(kept["reason"], "before_restore_original")
        self.assertEqual([p["name"] for p in kept["strategy"]["players"]], ["Juan Soto", "Aaron Judge"])
        back = v2.restore_from_trash(self.s, kept["trash_id"])          # the newer work comes back as a copy
        self.assertNotEqual(back["id"], "A")
        self.assertIn("(restored)", back["name"])

    def test_the_old_store_delete_is_recoverable_too(self) -> None:
        dss.delete_strategy(self.s, "B", confirmed=True)
        self.assertEqual(len(v2.list_trash(self.s)), 1)


class IdTests(unittest.TestCase):
    POOL = pd.DataFrame([{"fullName": "Will Smith", "MLBAM ID": 669257}, {"fullName": "Will Smith", "MLBAM ID": 519293},
                         {"fullName": "Kyle Tucker", "MLBAM ID": 663656}, {"fullName": "No Id Guy"}])

    def test_unique_pool_ids_seed_map_and_ambiguity(self) -> None:
        self.assertEqual(ids.resolve("Kyle Tucker", self.POOL), ("663656", "ok"))
        self.assertEqual(ids.resolve("Will Smith", self.POOL), ("", "ambiguous"))
        self.assertEqual(ids.resolve("Aaron Judge"), ("592450", "ok"))            # built-in seed map, offline
        with mock.patch("player_photos._load_mlbam_cache", return_value={}):
            self.assertEqual(ids.resolve("Nobody Known"), ("", ""))

    def test_resolution_never_uses_the_network(self) -> None:
        with mock.patch("player_photos._search_mlbam_via_api", side_effect=AssertionError("network")), \
                mock.patch("player_photos._load_mlbam_cache", return_value={}):
            ids.resolve("Somebody New", self.POOL)

    def test_notes_are_found_by_id_after_a_name_change(self) -> None:
        s = v2.new_strategy("S", queue=[ids.with_ids({"name": "Ronald Acuna Jr."})], at=T0)
        self.assertEqual(s["queue"][0]["mlbam_id"], "660670")
        s = v2.set_note(s, "Ronald Acuna Jr.", "steals")
        self.assertEqual(v2.note_for(s, "Ronald Acuña Jr.", "660670")["text"], "steals")
        self.assertEqual(v2.note_for(s, "Ronald Acuna Jr.")["text"], "steals")   # by name still works

    def test_ambiguous_entries_keep_name_keyed_notes(self) -> None:
        s = v2.new_strategy("S", queue=[ids.with_ids({"name": "Will Smith"}, self.POOL)], at=T0)
        self.assertEqual((s["queue"][0]["mlbam_id"], s["queue"][0]["id_status"]), ("", "ambiguous"))
        s = v2.set_note(s, "Will Smith", "which one?")
        self.assertNotIn("mlbam_id", s["notes"]["will smith"])

    def test_old_name_keyed_notes_still_load(self) -> None:
        s = v2.upgrade(_v1("A", "Alpha", [("Aaron Judge", "power")]))
        self.assertEqual(v2.note_for(s, "Aaron Judge", "592450")["text"], "power")


class WorkingCopyTests(_Base):
    def global_state(self) -> dict:
        return copy.deepcopy({k: self.s.get(k) for k in (DRAFT_QUEUE_KEY, "_queue_player_meta",
                                                          "_draft_strategy_loaded", "draft_queue_plan")})

    def test_edits_save_switch_delete_and_restore_never_touch_others(self) -> None:
        g, b = self.global_state(), copy.deepcopy(self.rows["B"])
        work.open_strategy(self.s, "A")
        work.edit(self.s, "A", v2.remove, "Juan Soto")
        work.open_strategy(self.s, "B")                      # switch: A keeps its unsaved edit
        self.assertEqual(work.dirty_ids(self.s), ["A"])
        self.assertEqual(self.rows["B"], b)
        work.open_strategy(self.s, "A")
        work.save(self.s, "A")
        self.assertEqual([p["name"] for p in self.rows["A"]["players"]], ["Aaron Judge", "Bobby Witt"])
        row = v2.soft_delete(self.s, "A", confirmed=True)
        v2.restore_from_trash(self.s, row["trash_id"])
        self.assertEqual(self.rows["B"], b)
        self.assertEqual(self.global_state(), g)

    def test_a_save_over_newer_work_is_refused(self) -> None:
        work.open_strategy(self.s, "A")
        work.edit(self.s, "A", v2.remove, "Juan Soto")
        other = {DRAFT_QUEUE_KEY: []}
        work.open_strategy(other, "A")
        work.edit(other, "A", v2.remove, "Bobby Witt")
        work.save(other, "A")
        with self.assertRaises(dss.StrategyError):
            work.save(self.s, "A")
        self.assertTrue(work.is_dirty(self.s, "A"))         # the user's edit is still there to redo

    def test_copy_global_into_counts_confirmation_and_modes(self) -> None:
        work.open_strategy(self.s, "A")
        p = work.preview_copy_global(self.s, "A", mode="replace")
        self.assertEqual((p["added"], p["removed"], p["kept"], p["needs_confirmation"]), (2, 3, 0, True))
        with self.assertRaises(dss.StrategyError):
            work.copy_global_into(self.s, "A", mode="replace")
        g = self.global_state()
        work.copy_global_into(self.s, "A", mode="append")      # nothing removed or reordered: no prompt
        self.assertEqual([e["name"] for e in work.current(self.s)["strategy"]["queue"]],
                         ["Aaron Judge", "Juan Soto", "Bobby Witt", "Global One", "Global Two"])
        work.discard(self.s, "A")
        work.open_strategy(self.s, "A")
        work.copy_global_into(self.s, "A", mode="replace", confirmed=True)
        self.assertEqual([e["name"] for e in work.current(self.s)["strategy"]["queue"]], ["Global One", "Global Two"])
        self.assertEqual(self.global_state(), g)
        self.assertEqual(self.rows["A"]["schema_version"], 1)     # not saved until the user saves

    def test_replace_global_with_counts_and_confirmation(self) -> None:
        a = copy.deepcopy(self.rows["A"])
        work.open_strategy(self.s, "A")
        p = work.preview_replace_global(self.s, "A")
        self.assertEqual((p["added"], p["removed"], p["needs_confirmation"]), (3, 2, True))
        with self.assertRaises(dss.StrategyError):
            work.replace_global_with(self.s, "A")
        self.assertEqual(self.s[DRAFT_QUEUE_KEY], ["Global One", "Global Two"])
        work.replace_global_with(self.s, "A", confirmed=True)
        self.assertEqual(self.s[DRAFT_QUEUE_KEY], ["Aaron Judge", "Juan Soto", "Bobby Witt"])
        self.assertTrue(self.s.get(dqm.SAVE_PENDING_KEY))       # saved with the workspace (draft_edit)
        self.assertEqual(self.rows["A"], a)

    def test_working_copies_are_cleared_on_account_change(self) -> None:
        from draft_queue_contract import clear_queue_for_account_change

        work.open_strategy(self.s, "A")
        work.edit(self.s, "A", v2.remove, "Juan Soto")
        clear_queue_for_account_change(self.s)
        self.assertNotIn(work.WORK_KEY, self.s)
        self.assertNotIn(work.OPEN_KEY, self.s)


class DraftPlanTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        from tests.test_draft_queue_modes import _room, _session

        self.room = _room()
        self.s.update(_session(self.room, queue=["Speed One", "Speed Two", "Power Bat"]))
        self.rows["P"] = _v1("P", "Power plan", [("Power Bat", "big power"), ("Contact C", ""), ("Speed Six", "")])
        self.rows["P"]["approach"] = "roster_aware"
        v2.append_research(self.s, "P", "Contact C walks a lot", player="Contact C")
        self.view = dqm.refresh(self.s, self.room, "Team A")
        self.source = self.view["source"]

    def test_a_strategy_plan_drives_fixed_and_leaves_the_masters_alone(self) -> None:
        g = list(self.s[DRAFT_QUEUE_KEY])
        p = copy.deepcopy(self.rows["P"])
        msg = dps.choose(self.s, self.source, "P")
        self.assertIn("not changed", msg)
        self.assertEqual(self.s["draft_strategy_approach"], "roster_aware")
        view = dqm.refresh(self.s, self.room, "Team A")
        self.assertEqual(view["fixed"], ["Power Bat", "Contact C", "Speed Six"])
        self.assertEqual(view["plan_source"]["name"], "Power plan")
        self.assertEqual(view["snapshot"]["players"], ["Power Bat", "Contact C", "Speed Six"])
        self.assertEqual(view["snapshot"]["saved_strategy"]["name"], "Power plan")
        self.s[dqm.MODE_KEY] = "adaptive"
        view = dqm.refresh(self.s, self.room, "Team A")
        self.assertEqual(sorted(view["adaptive"]), sorted(["Power Bat", "Contact C", "Speed Six"]))
        self.assertEqual(self.s[DRAFT_QUEUE_KEY], g)
        self.assertEqual(self.rows["P"], p)

    def test_pins_notes_and_research_come_from_the_plan_copy(self) -> None:
        dps.choose(self.s, self.source, "P")
        plan = dps.current(self.s, self.source)
        self.assertEqual(dps.notes(plan)["power bat"], "big power")
        self.assertEqual(dps.notes(plan)["contact c"], "Research: Contact C walks a lot")
        dps.set_pins(self.s, self.source, ["Speed Six"])
        self.assertEqual(self.s["draft_queue_plan"]["pins"], [])   # the Global Queue's pins are untouched
        self.assertEqual(self.rows["P"]["schema_version"], 1)       # the saved strategy is untouched

    def test_save_back_is_explicit_and_revision_checked(self) -> None:
        dps.choose(self.s, self.source, "P")
        dps.set_note(self.s, self.source, "Speed Six", "late steals")
        dps.add_player(self.s, self.source, "Speed One")
        with self.assertRaises(dss.StrategyError):
            dps.save_back(self.s, self.source, confirmed=False)
        saved = dps.save_back(self.s, self.source, confirmed=True)
        self.assertEqual([e["name"] for e in saved["queue"]], ["Power Bat", "Contact C", "Speed Six", "Speed One"])
        self.assertEqual(saved["notes"]["speed six"]["text"], "late steals")
        # Someone else changes the strategy: this draft's copy may not overwrite it.
        other = v2.get_strategy_v2(self.s, "P")
        v2.save_strategy_v2(self.s, v2.remove(other, "Contact C"), other["revision"])
        dps.set_note(self.s, self.source, "Power Bat", "changed")
        with self.assertRaises(dss.StrategyError):
            dps.save_back(self.s, self.source, confirmed=True)

    def test_back_to_the_global_queue(self) -> None:
        dps.choose(self.s, self.source, "P")
        dps.choose(self.s, self.source, dps.GLOBAL)
        view = dqm.refresh(self.s, self.room, "Team A")
        self.assertEqual(view["plan_source"], {"kind": "global"})
        self.assertEqual(view["fixed"], [n for n in self.s[DRAFT_QUEUE_KEY] if n in view["fixed"]])

    def test_restore_original_plan_resets_the_draft_copy_not_the_global_queue(self) -> None:
        dps.choose(self.s, self.source, "P")
        dqm.refresh(self.s, self.room, "Team A")
        dps.add_player(self.s, self.source, "Speed One")
        g = list(self.s[DRAFT_QUEUE_KEY])
        dqm.restore_snapshot_to_queue(self.s, confirmed=True)
        self.assertEqual(dps.plan_queue(self.s, self.source), ["Power Bat", "Contact C", "Speed Six"])
        self.assertEqual(self.s[DRAFT_QUEUE_KEY], g)

    def test_plan_keys_never_reach_a_shared_room_document(self) -> None:
        from draft_room_shared_state import sanitize_shared_room_document, shared_room_document_private_leaks

        dps.choose(self.s, self.source, "P")
        doc = {"draft_room_id": "R", work.WORK_KEY: {"P": {}}, work.OPEN_KEY: "P", dps.KEY: {"kind": "strategy"},
               dqm.ADAPTIVE_KEY: copy.deepcopy(self.s[dqm.ADAPTIVE_KEY])}
        self.assertEqual(len(shared_room_document_private_leaks(doc)), 4)
        self.assertEqual(shared_room_document_private_leaks(sanitize_shared_room_document(dict(doc))), [])
        self.assertEqual(shared_room_document_private_leaks({k: v for k, v in self.room.items() if k != "pool"}), [])


class S0FloorTests(unittest.TestCase):
    """The S0 reader (17167e3, the Slice 0 release candidate and minimum rollback) with what S2 writes."""

    def _s0_store(self):
        src = subprocess.run(["git", "show", "17167e3:draft_strategy_store.py"], cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8", check=True).stdout
        spec = importlib.util.spec_from_loader("s0_store", loader=None)
        mod = importlib.util.module_from_spec(spec)
        exec(compile(src, "s0_store.py", "exec"), mod.__dict__)
        sys.modules["s0_store"] = mod
        return mod

    def test_s0_lists_and_loads_s2_rows_and_never_sees_deleted_ones(self) -> None:
        s0 = self._s0_store()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "draft_strategies.json"
            with mock.patch("draft_strategy_store._LocalBackend._path", lambda _self: path), \
                    mock.patch.object(s0._LocalBackend, "_path", lambda _self: path), \
                    mock.patch("suite_storage_config.cloud_storage_enabled", return_value=False), \
                    mock.patch("suite_auth.is_auth_enabled", return_value=False):
                session = {DRAFT_QUEUE_KEY: []}
                big = v2.new_strategy("Big", queue=[ids.with_ids({"name": f"Player {i}"}) for i in range(250)] +
                                      [ids.with_ids({"name": "Aaron Judge"})])
                big = v2.set_note(big, "Aaron Judge", "power")
                v2.save_strategy_v2(session, big, None)
                gone = v2.new_strategy("Gone", queue=["Juan Soto"])
                v2.save_strategy_v2(session, gone, None)
                v2.soft_delete(session, gone["id"], confirmed=True)
                listed = s0.list_strategies(session)
                self.assertEqual([s["name"] for s in listed], ["Big"])     # deleted stays hidden on S0
                self.assertEqual(len(listed[0]["players"]), 251)            # no S0-side cap
                s0.load_strategy(session, big["id"])
                self.assertEqual(len(session[DRAFT_QUEUE_KEY]), 251)
                self.assertEqual(session["_draft_strategy_loaded"]["notes"], {"Aaron Judge": "power"})
                raw = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(set(raw), {big["id"]})                     # trash lives in its own file


if __name__ == "__main__":
    unittest.main()
