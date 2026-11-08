"""Pro Draft Strategy S1 (2026-11-08): the v2 strategy store, not yet wired into the UI.

Each strategy is its own queue. v1 rows upgrade in memory and are only written as v2 after the
user's first edit (with a one-time v1 backup first); saves are refused when the stored strategy
changed since the edit began; the global working queue is never touched.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import baseball_monetization as bm
import draft_strategy_store as dss
import draft_strategy_v2 as v2
from draft_state import DRAFT_QUEUE_KEY

T0 = "2026-11-01T10:00:00+00:00"


def _v1(sid: str, name: str, players: list[tuple[str, str]], **extra) -> dict:
    return {"schema_version": 1, "id": sid, "name": name, "approach": "value_based",
            "players": [{"rank": i, "name": n, "player_id": f"id{i}", "position": "OF", "note": note}
                        for i, (n, note) in enumerate(players, start=1)],
            "explanations": ["why"], "context": {"room_team_count": 12}, "created_at": T0, "updated_at": T0, **extra}


class _Backend:
    """In-memory rows of one item type. ``all`` can serve a stale per-session snapshot, like the
    cloud read cache; ``fetch`` is always fresh."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.puts: list[str] = []
        self.cached: list[dict] | None = None
        self.fail_put = False

    def put(self, key, title, payload):
        if self.fail_put:
            raise ConnectionError("offline")
        self.puts.append(key)
        self.rows[key] = copy.deepcopy(payload)

    def all(self):
        return copy.deepcopy(self.cached if self.cached is not None else list(self.rows.values()))

    def fetch(self, key):
        return copy.deepcopy(self.rows.get(key))

    def delete(self, key):
        self.rows.pop(key, None)


GLOBAL_KEYS = (DRAFT_QUEUE_KEY, "_queue_player_meta", "_draft_strategy_loaded", "draft_queue_plan")


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.backends = {t: _Backend() for t in (v2.ITEM_TYPE, v2.BACKUP_ITEM_TYPE, v2.RESEARCH_ITEM_TYPE)}
        for p in (mock.patch("draft_strategy_store._backend", side_effect=lambda t=v2.ITEM_TYPE: self.backends[t]),
                  mock.patch("suite_auth.is_auth_enabled", return_value=False)):
            p.start()
            self.addCleanup(p.stop)
        self.rows = self.backends[v2.ITEM_TYPE].rows
        self.rows["A"] = _v1("A", "Alpha", [("Aaron Judge", "power"), ("Juan Soto", ""), ("Bobby Witt", "")])
        self.rows["B"] = _v1("B", "Bravo", [("Kyle Tucker", "")])
        self.s = {DRAFT_QUEUE_KEY: ["Global One", "Global Two"],
                  "_queue_player_meta": {"global one": {"player_id": "g1", "position": "C", "team": "SEA"}},
                  "_draft_strategy_loaded": {"id": "B", "name": "Bravo", "notes": {}, "queue": ["Kyle Tucker"]},
                  "draft_queue_plan": {"pins": ["Global One"], "notes": {"global two": "x"}, "moves": []}}

    def assertMirror(self, s: dict) -> None:
        self.assertEqual(s["players"], [
            {"rank": i, "name": e["name"], "player_id": e["player_id"], "position": e["position"],
             "note": (s["notes"].get(e["name"].lower()) or {}).get("text", "")}
            for i, e in enumerate(s["queue"], start=1)])

    def global_state(self) -> dict:
        return copy.deepcopy({k: self.s.get(k) for k in GLOBAL_KEYS})


class UpgradeTests(_Base):
    def test_v1_upgrades_to_a_superset_in_memory(self) -> None:
        raw = copy.deepcopy(self.rows["A"])
        s = v2.upgrade(raw)
        self.assertEqual(raw, self.rows["A"])  # input not mutated
        self.assertEqual(s["schema_version"], 2)
        self.assertEqual(s["revision"], 0)
        self.assertEqual([e["name"] for e in s["queue"]], ["Aaron Judge", "Juan Soto", "Bobby Witt"])
        self.assertEqual(s["queue"][0], {"name": "Aaron Judge", "player_id": "id1", "position": "OF", "team": "",
                                         "added_at": T0, "source": "v1"})
        self.assertEqual(s["notes"], {"aaron judge": {"text": "power", "updated_at": T0, "source": "user"}})
        self.assertEqual(s["players"], self.rows["A"]["players"])  # the v1 mirror is exactly the v1 list
        for key in ("id", "name", "approach", "context", "explanations", "created_at", "updated_at"):
            self.assertEqual(s[key], self.rows["A"][key])
        self.assertEqual(s["provenance"], {"migrated_from": 1, "migrated_at": None, "created_from": "v1_snapshot"})
        self.assertEqual((s["pins"], s["priorities"], s["preferences"], s["settings"], s["edits"]), ([], {}, {}, {}, []))

    def test_upgrade_is_idempotent(self) -> None:
        messy = _v1("M", "Messy", [("B Guy", "n1"), ("A Guy", ""), ("b guy", "dup")])
        messy["players"][0]["rank"] = 3  # out of order
        for row in (self.rows["A"], messy, v2.set_note(v2.pin(v2.upgrade(self.rows["A"]), "Juan Soto"), "Bobby Witt", "speed")):
            once = v2.upgrade(row)
            self.assertEqual(v2.upgrade(once), once)
            self.assertEqual(v2.upgrade(copy.deepcopy(once)), once)
            self.assertMirror(once)
        self.assertEqual([e["name"] for e in v2.upgrade(messy)["queue"]], ["A Guy", "B Guy"])  # by rank, deduped

    def test_upgrade_dedupes_by_player_key(self) -> None:
        row = _v1("D", "Dups", [("A Guy", ""), ("a guy", ""), ("B Guy", "")])
        self.assertEqual([e["name"] for e in v2.upgrade(row)["queue"]], ["A Guy", "B Guy"])

    def test_an_older_release_editing_the_mirror_is_adopted(self) -> None:
        s = v2.upgrade(self.rows["A"])
        s = v2.pin(s, "Juan Soto")
        # S0 update_strategy on a v2 row: players replaced, revision untouched, updated_at changes.
        legacy = {**copy.deepcopy(s), "updated_at": "2026-11-05T00:00:00+00:00",
                  "players": [{"rank": 1, "name": "Juan Soto", "player_id": "", "position": "", "note": "patient"},
                              {"rank": 2, "name": "New Guy", "player_id": "n1", "position": "SP", "note": ""}]}
        up = v2.upgrade(legacy)
        self.assertEqual([e["name"] for e in up["queue"]], ["Juan Soto", "New Guy"])
        self.assertEqual(up["queue"][0]["player_id"], "id2")       # kept from the v2 entry
        self.assertEqual(up["queue"][1]["source"], "v1_writer")
        self.assertEqual(up["notes"]["juan soto"]["text"], "patient")
        self.assertEqual(up["notes"]["aaron judge"]["text"], "power")  # research notes are kept
        self.assertEqual(up["pins"], ["juan soto"])
        self.assertEqual(v2.upgrade(up), up)
        self.assertMirror(up)


class OperationTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.base = v2.upgrade(self.rows["A"])

    def test_each_op_bumps_revision_logs_and_keeps_the_mirror(self) -> None:
        s = self.base
        steps = [
            (v2.move, ("Bobby Witt", 0)),
            (v2.insert, ({"name": "Kyle Tucker", "player_id": "k1", "position": "OF", "team": "HOU"}, 1)),
            (v2.set_note, ("Kyle Tucker", "steady")),
            (v2.pin, ("Kyle Tucker",)),
            (v2.remove, ("Juan Soto",)),
            (v2.unpin, ("Kyle Tucker",)),
            (v2.set_settings, ({"rounds": 23},)),
            (v2.set_preferences, ({"avoid": ["NYY"]},)),
            (v2.rename, ("Alpha 2027",)),
        ]
        for n, (op, args) in enumerate(steps, start=1):
            prev, snapshot = s, copy.deepcopy(s)
            s = op(prev, *args, at=f"t{n}")
            self.assertEqual(prev, snapshot)  # ops are pure: the input is unchanged
            self.assertEqual(s["revision"], n)
            self.assertEqual(s["edits"][-1]["rev"], n)
            self.assertEqual(s["edits"][-1]["at"], f"t{n}")
            self.assertEqual(s["edits"][-1]["actor"], "user")
            self.assertMirror(s)
        self.assertEqual([e["name"] for e in s["queue"]], ["Bobby Witt", "Kyle Tucker", "Aaron Judge"])
        self.assertEqual(s["queue"][1]["team"], "HOU")
        self.assertEqual(s["players"][1]["note"], "steady")
        self.assertEqual((s["pins"], s["settings"], s["preferences"], s["name"]),
                         ([], {"rounds": 23}, {"avoid": ["NYY"]}, "Alpha 2027"))
        self.assertEqual(s["updated_at"], T0)  # only a save changes it
        self.assertEqual(self.base, v2.upgrade(self.rows["A"]))

    def test_ops_do_not_mutate_their_input(self) -> None:
        frozen = copy.deepcopy(self.base)
        v2.move(self.base, "Bobby Witt", 0)
        v2.set_note(self.base, "Juan Soto", "x")
        v2.remove(self.base, "Aaron Judge")
        self.assertEqual(self.base, frozen)

    def test_no_op_edits_do_not_bump_the_revision(self) -> None:
        self.assertEqual(v2.move(self.base, "Aaron Judge", 0)["revision"], 0)
        self.assertEqual(v2.set_note(self.base, "Aaron Judge", "power")["revision"], 0)
        self.assertEqual(v2.unpin(self.base, "Juan Soto")["revision"], 0)
        self.assertEqual(v2.set_settings(self.base, {"gone": None})["revision"], 0)

    def test_note_sources_and_removal(self) -> None:
        s = v2.set_note(self.base, "Juan Soto", "AMI says patient", source="ami_confirmed", actor="ami_confirmed")
        self.assertEqual(s["notes"]["juan soto"]["source"], "ami_confirmed")
        self.assertEqual(s["edits"][-1]["actor"], "ami_confirmed")
        s = v2.set_note(s, "Aaron Judge", "")
        self.assertNotIn("aaron judge", s["notes"])
        self.assertEqual(s["players"][0]["note"], "")
        with self.assertRaises(dss.StrategyError):
            v2.set_note(s, "Juan Soto", "x", source="robot")

    def test_remove_unpins_but_keeps_research_notes(self) -> None:
        s = v2.remove(v2.pin(self.base, "Aaron Judge"), "Aaron Judge")
        self.assertEqual(s["pins"], [])
        self.assertEqual(s["notes"]["aaron judge"]["text"], "power")
        self.assertNotIn("Aaron Judge", [p["name"] for p in s["players"]])

    def test_move_clamps_and_unknown_players_are_refused(self) -> None:
        self.assertEqual(v2.move(self.base, "aaron judge", 99)["queue"][-1]["name"], "Aaron Judge")
        self.assertEqual(v2.move(self.base, "Bobby Witt", -5)["queue"][0]["name"], "Bobby Witt")
        for op, args in ((v2.move, ("Nobody", 0)), (v2.remove, ("Nobody",)), (v2.pin, ("Nobody",)),
                         (v2.insert, ("juan soto",)), (v2.insert, ("  ",))):
            with self.assertRaises(dss.StrategyError):
                op(self.base, *args)

    def test_edit_log_keeps_the_last_50(self) -> None:
        s = self.base
        for i in range(60):
            s = v2.set_settings(s, {"n": i}, at=f"t{i}")
        self.assertEqual(s["revision"], 60)
        self.assertEqual(len(s["edits"]), v2.EDITS_MAX)
        self.assertEqual([e["rev"] for e in s["edits"]], list(range(11, 61)))

    def test_bad_settings_are_refused(self) -> None:
        for bad in ({"": 1}, {"x" * 41: 1}, {"k": {"nested": 1}}, {"k": object()}, ["not", "a", "dict"]):
            with self.assertRaises(dss.StrategyError):
                v2.set_settings(self.base, bad)


class CapTests(_Base):
    def test_queue_note_and_pin_caps(self) -> None:
        s = v2.new_strategy("Big", queue=[f"P{i}" for i in range(v2.QUEUE_MAX)], at=T0)
        with self.assertRaises(dss.StrategyError) as ctx:
            v2.insert(s, "One More")
        self.assertIn(str(v2.QUEUE_MAX), str(ctx.exception))
        with self.assertRaises(dss.StrategyError):
            v2.new_strategy("Too big", queue=[f"P{i}" for i in range(v2.QUEUE_MAX + 1)])
        with self.assertRaises(dss.StrategyError):
            v2.set_note(s, "P1", "x" * (v2.NOTE_MAX + 1))
        for i in range(v2.PINS_MAX):
            s = v2.pin(s, f"P{i}")
        with self.assertRaises(dss.StrategyError):
            v2.pin(s, f"P{v2.PINS_MAX}")

    def test_size_cap_is_a_clear_error_and_saves_nothing(self) -> None:
        s = v2.upgrade(self.rows["A"])
        s = v2.set_preferences(s, {f"k{i}": "x" * 400 for i in range(40)})  # ~16 KB
        with self.assertRaises(dss.StrategyError) as ctx:
            v2.set_preferences(s, {f"j{i}": "y" * 400 for i in range(45)})
        self.assertIn("too large to save", str(ctx.exception))
        self.assertIn("32 KB", str(ctx.exception))
        oversized = {**s, "explanations": ["z" * 200] * 20, "context": {"blob": "q" * 30000}}
        with self.assertRaises(dss.StrategyError):
            v2.save_strategy_v2(self.s, v2.set_settings(oversized, {"a": 1}), 0)
        self.assertEqual(self.backends[v2.ITEM_TYPE].puts, [])
        self.assertEqual(self.backends[v2.BACKUP_ITEM_TYPE].puts, [])


class SaveTests(_Base):
    def test_reading_never_writes_and_unedited_saves_do_nothing(self) -> None:
        v2.list_strategies_v2(self.s)
        a = v2.get_strategy_v2(self.s, "A")
        self.assertEqual(v2.save_strategy_v2(self.s, a, 0)["revision"], 0)
        self.assertEqual(self.backends[v2.ITEM_TYPE].puts, [])
        self.assertEqual(self.backends[v2.BACKUP_ITEM_TYPE].puts, [])
        self.assertEqual(self.rows["A"]["schema_version"], 1)

    def test_first_edit_backs_up_v1_exactly_once_then_writes_v2(self) -> None:
        original = copy.deepcopy(self.rows["A"])
        a = v2.get_strategy_v2(self.s, "A")
        saved = v2.save_strategy_v2(self.s, v2.move(a, "Bobby Witt", 0), a["revision"])
        backups = self.backends[v2.BACKUP_ITEM_TYPE]
        self.assertEqual(backups.puts, ["A"])
        self.assertEqual(backups.rows["A"]["strategy"], original)
        self.assertEqual(backups.rows["A"]["backup_of"], "A")
        stored = self.rows["A"]
        self.assertEqual((stored["schema_version"], stored["revision"]), (2, 1))
        self.assertEqual([p["name"] for p in stored["players"]], ["Bobby Witt", "Aaron Judge", "Juan Soto"])
        self.assertEqual(stored["players"][1]["note"], "power")
        self.assertTrue(stored["provenance"]["migrated_at"])
        self.assertNotEqual(stored["updated_at"], T0)
        self.assertEqual(saved, stored)
        # Later edits never back up again.
        again = v2.save_strategy_v2(self.s, v2.set_note(saved, "Juan Soto", "walks"), saved["revision"])
        self.assertEqual(again["revision"], 2)
        self.assertEqual(backups.puts, ["A"])
        self.assertEqual(self.backends[v2.ITEM_TYPE].puts, ["A", "A"])
        self.assertEqual(v2.get_v1_backup(self.s, "A")["strategy"], original)

    def test_a_failed_first_write_keeps_the_single_backup(self) -> None:
        a = v2.get_strategy_v2(self.s, "A")
        edited = v2.move(a, "Bobby Witt", 0)
        self.backends[v2.ITEM_TYPE].fail_put = True
        with self.assertRaises(dss.StrategyError):
            v2.save_strategy_v2(self.s, edited, 0)
        self.assertEqual(self.rows["A"]["schema_version"], 1)
        self.backends[v2.ITEM_TYPE].fail_put = False
        v2.save_strategy_v2(self.s, edited, 0)
        self.assertEqual(self.backends[v2.BACKUP_ITEM_TYPE].puts, ["A"])
        self.assertEqual(self.rows["A"]["schema_version"], 2)

    def test_editing_one_strategy_leaves_the_other_and_the_global_queue_alone(self) -> None:
        before_b, before_global = copy.deepcopy(self.rows["B"]), self.global_state()
        before_session = copy.deepcopy(self.s)
        a = v2.get_strategy_v2(self.s, "A")
        for edit in (lambda x: v2.insert(x, "Kyle Tucker"), lambda x: v2.remove(x, "Juan Soto"),
                     lambda x: v2.set_note(x, "Kyle Tucker", "mine too"), lambda x: v2.pin(x, "Aaron Judge")):
            a = v2.save_strategy_v2(self.s, edit(a), a["revision"])
        v2.append_research(self.s, "A", "Tucker's exit velocity is up")
        self.assertEqual(self.rows["B"], before_b)
        self.assertEqual(self.global_state(), before_global)
        self.assertEqual(self.s, before_session)
        self.assertNotIn("B", self.backends[v2.BACKUP_ITEM_TYPE].rows)
        self.assertEqual([p["name"] for p in self.rows["A"]["players"]], ["Aaron Judge", "Bobby Witt", "Kyle Tucker"])

    def test_a_stale_revision_is_refused(self) -> None:
        tab1 = v2.get_strategy_v2(self.s, "A")
        tab2 = copy.deepcopy(tab1)
        first = v2.save_strategy_v2(self.s, v2.move(tab1, "Bobby Witt", 0), 0)
        with self.assertRaises(dss.StrategyError) as ctx:
            v2.save_strategy_v2(self.s, v2.remove(tab2, "Juan Soto"), 0)
        self.assertIn("changed somewhere else", str(ctx.exception))
        self.assertEqual(self.rows["A"], first)
        with self.assertRaises(dss.StrategyError):  # a wrong base for the right data
            v2.save_strategy_v2(self.s, v2.remove(first, "Juan Soto"), 0)
        self.assertEqual(self.rows["A"], first)

    def test_the_check_reads_fresh_not_the_session_cache(self) -> None:
        a = v2.get_strategy_v2(self.s, "A")
        saved = v2.save_strategy_v2(self.s, v2.move(a, "Bobby Witt", 0), 0)
        # Another device saves revision 2; this session's list cache still serves revision 1.
        self.backends[v2.ITEM_TYPE].cached = [copy.deepcopy(saved), copy.deepcopy(self.rows["B"])]
        other = v2.save_strategy_v2(self.s, v2.set_note(saved, "Juan Soto", "elsewhere"), 1)
        stale = v2.get_strategy_v2(self.s, "A")
        self.assertEqual(stale["revision"], 1)
        with self.assertRaises(dss.StrategyError):
            v2.save_strategy_v2(self.s, v2.remove(stale, "Juan Soto"), stale["revision"])
        self.assertEqual(self.rows["A"], other)

    def test_an_older_release_write_is_caught_by_updated_at(self) -> None:
        a = v2.get_strategy_v2(self.s, "A")
        saved = v2.save_strategy_v2(self.s, v2.move(a, "Bobby Witt", 0), 0)
        self.rows["A"] = {**copy.deepcopy(saved), "name": "Renamed by old app", "updated_at": "2026-11-09T00:00:00+00:00"}
        with self.assertRaises(dss.StrategyError):
            v2.save_strategy_v2(self.s, v2.remove(saved, "Juan Soto"), saved["revision"])

    def test_new_strategies_and_id_collisions(self) -> None:
        s = v2.new_strategy("Charlie", queue=["X One", {"name": "Y Two", "team": "LAD"}], created_from="research", at=T0)
        self.assertEqual(s["provenance"]["created_from"], "research")
        saved = v2.save_strategy_v2(self.s, s, None)
        self.assertEqual(self.rows[s["id"]], saved)
        self.assertEqual(self.backends[v2.BACKUP_ITEM_TYPE].puts, [])  # nothing to back up
        with self.assertRaises(dss.StrategyError):
            v2.save_strategy_v2(self.s, s, None)
        with self.assertRaises(dss.StrategyError):  # names stay unique
            v2.save_strategy_v2(self.s, v2.new_strategy("alpha"), None)

    def test_a_newer_schema_is_never_overwritten(self) -> None:
        self.rows["N"] = {**_v1("N", "Future", [("A Guy", "")]), "schema_version": 3, "revision": 4}
        n = v2.get_strategy_v2(self.s, "N")
        self.assertEqual(n["schema_version"], 3)
        with self.assertRaises(dss.StrategyError) as ctx:
            v2.save_strategy_v2(self.s, v2.insert(n, "B Guy"), 4)
        self.assertIn("newer version", str(ctx.exception))
        self.assertEqual(self.rows["N"]["revision"], 4)


class V1PathsOnV2RowsTests(_Base):
    def _v2_row(self) -> dict:
        a = v2.get_strategy_v2(self.s, "A")
        return v2.save_strategy_v2(self.s, v2.pin(a, "Juan Soto"), 0)

    def test_update_rename_duplicate_keep_v2_consistent(self) -> None:
        saved = self._v2_row()
        self.s[DRAFT_QUEUE_KEY] = ["Juan Soto", "Global One"]
        updated = dss.update_strategy(self.s, "A", confirm_overwrite=True, notes={"global one": "catcher"})
        self.assertEqual(updated["revision"], saved["revision"] + 2)  # replace_queue + set_note
        self.assertEqual([e["name"] for e in updated["queue"]], ["Juan Soto", "Global One"])
        self.assertEqual(updated["queue"][1]["team"], "SEA")
        self.assertEqual(updated["queue"][0]["added_at"], T0)        # kept its history
        self.assertEqual(updated["pins"], ["juan soto"])
        self.assertEqual(updated["notes"]["global one"]["text"], "catcher")
        self.assertMirror(updated)
        renamed = dss.rename_strategy(self.s, "A", "Alpha Prime")
        self.assertEqual((renamed["name"], renamed["revision"]), ("Alpha Prime", updated["revision"] + 1))
        dup = dss.duplicate_strategy(self.s, "A")
        self.assertEqual((dup["revision"], dup["edits"], dup["provenance"]["created_from"]), (0, [], "duplicate:A"))
        self.assertEqual(dup["queue"], renamed["queue"])
        self.assertEqual(self.backends[v2.BACKUP_ITEM_TYPE].puts, ["A"])

    def test_load_into_queue_still_works_from_a_v2_row(self) -> None:
        self._v2_row()
        dss.load_strategy(self.s, "A", confirm_replace=True)
        self.assertEqual(self.s[DRAFT_QUEUE_KEY], ["Aaron Judge", "Juan Soto", "Bobby Witt"])
        self.assertEqual(self.s["_draft_strategy_loaded"]["notes"], {"Aaron Judge": "power"})


class ResearchLogTests(_Base):
    def test_append_caps_and_separate_item_type(self) -> None:
        for i in range(v2.RESEARCH_MAX + 5):
            v2.append_research(self.s, "A", f"entry {i}", player="Aaron Judge", at=f"t{i}")
        log = v2.research_log(self.s, "A")
        self.assertEqual(len(log), v2.RESEARCH_MAX)
        self.assertEqual(log[0]["text"], "entry 5")
        self.assertEqual(log[-1], {"at": f"t{v2.RESEARCH_MAX + 4}", "kind": "note", "text": f"entry {v2.RESEARCH_MAX + 4}",
                                   "player_key": "aaron judge", "source": "user"})
        self.assertEqual(self.rows["A"]["schema_version"], 1)  # the strategy row is untouched
        self.assertEqual(v2.research_log(self.s, "B"), [])
        for bad in (("A", ""), ("A", "x" * (v2.RESEARCH_TEXT_MAX + 1)), ("missing", "hello")):
            with self.assertRaises(dss.StrategyError):
                v2.append_research(self.s, *bad)
        with self.assertRaises(dss.StrategyError):
            v2.append_research(self.s, "A", "x", source="robot")


class AccessTests(_Base):
    def test_guests_are_refused_everywhere(self) -> None:
        a = v2.upgrade(self.rows["A"])
        with mock.patch("suite_auth.is_anonymous_guest", return_value=True):
            for call in (lambda: v2.get_strategy_v2(self.s, "A"), lambda: v2.list_strategies_v2(self.s),
                         lambda: v2.save_strategy_v2(self.s, v2.move(a, "Bobby Witt", 0), 0),
                         lambda: v2.append_research(self.s, "A", "x"), lambda: v2.research_log(self.s, "A"),
                         lambda: v2.get_v1_backup(self.s, "A")):
                with self.assertRaises(dss.StrategyError) as ctx:
                    call()
                self.assertIn("Sign in", str(ctx.exception))
        self.assertEqual(self.backends[v2.ITEM_TYPE].puts + self.backends[v2.RESEARCH_ITEM_TYPE].puts, [])

    def test_pro_enforcement_blocks_free_and_allows_pro(self) -> None:
        a = v2.upgrade(self.rows["A"])
        enforced = frozenset({bm.FeatureId.DRAFT_STRATEGIES})
        with mock.patch.object(bm, "ENFORCED_FEATURES", enforced), \
                mock.patch("baseball_monetization_ui.current_entitlement", return_value=bm.EntitlementSnapshot()):
            with self.assertRaises(dss.StrategyError) as ctx:
                v2.save_strategy_v2(self.s, v2.move(a, "Bobby Witt", 0), 0)
            self.assertIn("Pro feature", str(ctx.exception))
        self.assertEqual(self.backends[v2.ITEM_TYPE].puts, [])
        with mock.patch.object(bm, "ENFORCED_FEATURES", enforced), \
                mock.patch("baseball_monetization_ui.current_entitlement",
                           return_value=bm.development_entitlement(bm.Plan.PRO)):
            self.assertEqual(v2.save_strategy_v2(self.s, v2.move(a, "Bobby Witt", 0), 0)["revision"], 1)


class BackendTests(unittest.TestCase):
    def test_local_backend_keeps_each_item_type_in_its_own_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            main = Path(tmp) / "draft_strategies.json"
            main.write_text(json.dumps({"A": _v1("A", "Alpha", [("Aaron Judge", "power"), ("Juan Soto", "")])}),
                            encoding="utf-8")
            with mock.patch("draft_strategy_store._LocalBackend._path", return_value=main), \
                    mock.patch("suite_storage_config.cloud_storage_enabled", return_value=False), \
                    mock.patch("suite_auth.is_auth_enabled", return_value=False):
                session = {DRAFT_QUEUE_KEY: ["Global"]}
                a = v2.get_strategy_v2(session, "A")
                saved = v2.save_strategy_v2(session, v2.move(a, "Juan Soto", 0), 0)
                v2.append_research(session, "A", "note")
                files = sorted(p.name for p in Path(tmp).iterdir())
                self.assertEqual(files, ["draft_strategies.json", "draft_strategy_research.json",
                                         "draft_strategy_v1_backup.json"])
                self.assertEqual(json.loads(main.read_text(encoding="utf-8"))["A"]["revision"], 1)
                self.assertEqual(v2.get_v1_backup(session, "A")["strategy"]["schema_version"], 1)
                self.assertEqual(v2.get_strategy_v2(session, "A"), saved)
                self.assertEqual([s["id"] for s in dss.list_strategies(session)], ["A"])  # no backup rows listed
                self.assertEqual(session, {DRAFT_QUEUE_KEY: ["Global"]})

    def test_cloud_fetch_bypasses_the_read_cache(self) -> None:
        with mock.patch("suite_storage_supabase.load_saved_items",
                        return_value=[{"payload": {"id": "k", "revision": 3}}]) as load:
            self.assertEqual(dss._CloudBackend(v2.BACKUP_ITEM_TYPE).fetch("k"), {"id": "k", "revision": 3})
        kw = load.call_args.kwargs
        self.assertEqual((kw["item_type"], kw["item_key"], kw["use_cache"]), (v2.BACKUP_ITEM_TYPE, "k", False))
        with mock.patch("suite_storage_supabase.load_saved_items", return_value=[]):
            self.assertIsNone(dss._CloudBackend().fetch("k"))

    def test_load_saved_items_passes_item_key_and_cache_choice(self) -> None:
        import suite_storage_supabase as sss

        with mock.patch.object(sss, "_request", return_value=[]) as req, \
                mock.patch.object(sss, "_scoped_user_id", return_value="u1"), \
                mock.patch.object(sss, "_scoped_storage_app", return_value="baseball"), \
                mock.patch.object(sss, "_workspace_storage_app_keys", return_value=["baseball"]):
            sss.load_saved_items(app="baseball", item_type="draft_strategy", item_key="k", limit=1, use_cache=False)
            self.assertEqual(req.call_args.kwargs["params"]["item_key"], "eq.k")
            self.assertIs(req.call_args.kwargs["use_cache"], False)
            sss.load_saved_items(app="baseball", item_type="draft_strategy")
            self.assertNotIn("item_key", req.call_args.kwargs["params"])
            self.assertIsNone(req.call_args.kwargs["use_cache"])


if __name__ == "__main__":
    unittest.main()
