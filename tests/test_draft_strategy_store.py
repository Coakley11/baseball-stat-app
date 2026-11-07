"""Saved Draft Strategies (Draft Strategy Assistant Phase 1, 2026-10-27).

A strategy is a snapshot of the working queue: drafting consumes the queue but never the
strategy; loading replaces the whole queue (after confirmation when it is not empty).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import baseball_monetization as bm
import draft_strategy_store as dss
from draft_state import DRAFT_QUEUE_KEY

TEN = [f"Player {i:02d}" for i in range(1, 11)]


class _MemoryBackend:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.fail = False

    def put(self, key, title, payload):
        if self.fail:
            raise ConnectionError("offline")
        self.rows[key] = payload

    def all(self):
        if self.fail:
            raise ConnectionError("offline")
        return list(self.rows.values())

    def delete(self, key):
        self.rows.pop(key, None)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = _MemoryBackend()
        for p in (mock.patch("draft_strategy_store._backend", return_value=self.backend),
                  mock.patch("suite_auth.is_auth_enabled", return_value=False)):
            p.start()
            self.addCleanup(p.stop)
        self.s = {DRAFT_QUEUE_KEY: list(TEN), "room_format": "5x5 Roto", "room_team_count": 4}


class SnapshotTests(_Base):
    def test_drafting_marks_the_queue_and_never_changes_the_strategy(self) -> None:
        import draft_room_state as drs
        from draft_actions import _prune_drafted_from_queue

        s = self.s
        s.update({"room_team_names": "A\nB\nC\nD", "room_rounds": 5, "room_your_team": "A"})
        drs.ensure_simulator_board_for_settings(s)
        strategy = dss.save_strategy(s, "Draft Strategy 1", notes={"Player 01": "elite power"})
        for player in TEN[:8]:
            df = drs.ensure_runtime_draft_board(s)
            label = drs.open_pick_row_options(df)[0][1]
            drs.submit_board_pick_assignment(s, pick_label=label, player_match=player,
                                             pick_row_by_label=drs.pick_label_row_map(df), all_names=[player])
            _prune_drafted_from_queue(s)
        # Owner decision 2026-11-06: picks never delete from the personal queue; this draft marks them.
        from draft_queue_contract import split_queue_for_active_draft

        self.assertEqual(s[DRAFT_QUEUE_KEY], TEN)
        self.assertEqual(split_queue_for_active_draft(s), (TEN[8:], TEN[:8]))
        saved = dss.get_strategy(s, strategy["id"])
        self.assertEqual([p["name"] for p in saved["players"]], TEN)
        self.assertEqual(saved["players"][0]["note"], "elite power")
        self.assertEqual(saved["context"]["room_format"], "5x5 Roto")

        result = dss.load_strategy(s, strategy["id"])  # queue not empty -> ask first
        self.assertTrue(result["needs_confirmation"])
        self.assertIn("replace your current 10-player queue with the 10 players", result["message"])
        self.assertEqual(s[DRAFT_QUEUE_KEY], TEN)  # unchanged until confirmed
        dss.load_strategy(s, strategy["id"], confirm_replace=True)
        self.assertEqual(s[DRAFT_QUEUE_KEY], TEN)  # replaced in saved order, not merged
        self.assertEqual([p["name"] for p in dss.get_strategy(s, strategy["id"])["players"]], TEN)

    def test_two_strategies_load_independently(self) -> None:
        one = dss.save_strategy(self.s, "Power Hitters")
        self.s[DRAFT_QUEUE_KEY] = ["Speed A", "Speed B"]
        two = dss.save_strategy(self.s, "Speed", approach="roster_aware")
        dss.load_strategy(self.s, one["id"], confirm_replace=True)
        self.assertEqual(self.s[DRAFT_QUEUE_KEY], TEN)
        dss.load_strategy(self.s, two["id"], confirm_replace=True)
        self.assertEqual(self.s[DRAFT_QUEUE_KEY], ["Speed A", "Speed B"])
        self.assertEqual(dss.get_strategy(self.s, two["id"])["approach"], "roster_aware")

    def test_empty_queue_loads_without_asking(self) -> None:
        strategy = dss.save_strategy(self.s, "S")
        self.s[DRAFT_QUEUE_KEY] = []
        self.assertFalse(dss.load_strategy(self.s, strategy["id"])["needs_confirmation"])
        self.assertEqual(self.s[DRAFT_QUEUE_KEY], TEN)

    def test_context_difference_warns(self) -> None:
        strategy = dss.save_strategy(self.s, "S")
        self.s["room_team_count"] = 12
        warnings = dss.load_strategy(self.s, strategy["id"], confirm_replace=True)["warnings"]
        self.assertTrue(any("number of teams 4" in w for w in warnings), warnings)


class LibraryTests(_Base):
    def test_rename_duplicate_update_delete(self) -> None:
        s = self.s
        a = dss.save_strategy(s, "Alpha")
        with self.assertRaises(dss.StrategyError):
            dss.save_strategy(s, "alpha")  # names are unique
        dss.rename_strategy(s, a["id"], "Alpha 2027")
        copy_ = dss.duplicate_strategy(s, a["id"])
        self.assertEqual(copy_["name"], "Alpha 2027 (copy)")
        self.assertNotEqual(copy_["id"], a["id"])
        s[DRAFT_QUEUE_KEY] = ["New Guy"]
        with self.assertRaises(dss.StrategyError):
            dss.update_strategy(s, a["id"], confirm_overwrite=False)
        self.assertEqual(len(dss.get_strategy(s, a["id"])["players"]), 10)
        dss.update_strategy(s, a["id"], confirm_overwrite=True)
        self.assertEqual([p["name"] for p in dss.get_strategy(s, a["id"])["players"]], ["New Guy"])
        self.assertEqual(len(dss.get_strategy(s, copy_["id"])["players"]), 10)  # the copy is independent
        with self.assertRaises(dss.StrategyError):
            dss.delete_strategy(s, a["id"], confirmed=False)
        dss.delete_strategy(s, a["id"], confirmed=True)
        self.assertEqual([x["id"] for x in dss.list_strategies(s)], [copy_["id"]])

    def test_saving_an_empty_queue_is_refused(self) -> None:
        self.s[DRAFT_QUEUE_KEY] = []
        with self.assertRaises(dss.StrategyError):
            dss.save_strategy(self.s, "Nothing")

    def test_store_failure_changes_nothing(self) -> None:
        strategy = dss.save_strategy(self.s, "S")
        self.s[DRAFT_QUEUE_KEY] = ["Keep Me"]
        self.backend.fail = True
        with self.assertRaises(dss.StrategyError) as ctx:
            dss.load_strategy(self.s, strategy["id"], confirm_replace=True)
        self.assertIn("nothing was changed", str(ctx.exception))
        self.assertEqual(self.s[DRAFT_QUEUE_KEY], ["Keep Me"])


class AccessTests(_Base):
    def test_signed_out_guest_cannot_use_strategies(self) -> None:
        with mock.patch("suite_auth.is_anonymous_guest", return_value=True):
            with self.assertRaises(dss.StrategyError):
                dss.save_strategy(self.s, "S")
        self.assertEqual(self.backend.rows, {})

    def test_pro_enforcement_blocks_free_and_allows_pro(self) -> None:
        enforced = frozenset({bm.FeatureId.DRAFT_STRATEGIES})
        with mock.patch.object(bm, "ENFORCED_FEATURES", enforced), \
                mock.patch("baseball_monetization_ui.current_entitlement", return_value=bm.EntitlementSnapshot()):
            with self.assertRaises(dss.StrategyError) as ctx:
                dss.save_strategy(self.s, "S")
            self.assertIn("Pro feature", str(ctx.exception))
        pro = bm.development_entitlement(bm.Plan.PRO)
        with mock.patch.object(bm, "ENFORCED_FEATURES", enforced), \
                mock.patch("baseball_monetization_ui.current_entitlement", return_value=pro):
            self.assertTrue(dss.save_strategy(self.s, "S")["id"])


class BackendTests(unittest.TestCase):
    def test_cloud_backend_uses_account_scoped_saved_items(self) -> None:
        with mock.patch("suite_storage_supabase.upsert_saved_item") as up, \
                mock.patch("suite_storage_supabase.load_saved_items", return_value=[{"payload": {"id": "x"}}]) as load, \
                mock.patch("suite_storage_supabase.invalidate_saved_item") as inv:
            b = dss._CloudBackend()
            b.put("k", "Name", {"id": "k"})
            self.assertEqual(b.all(), [{"id": "x"}])
            b.delete("k")
        self.assertEqual(up.call_args.args[:3], ("baseball", "draft_strategy", "k"))
        self.assertEqual(load.call_args.kwargs["item_type"], "draft_strategy")
        self.assertEqual(inv.call_args.args, ("baseball", "draft_strategy", "k"))

    def test_local_backend_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("draft_strategy_store._LocalBackend._path", return_value=Path(tmp) / "draft_strategies.json"):
                b = dss._LocalBackend()
                b.put("k", "Name", {"id": "k", "name": "Name"})
                self.assertEqual(b.all(), [{"id": "k", "name": "Name"}])
                b.delete("k")
                self.assertEqual(b.all(), [])


if __name__ == "__main__":
    unittest.main()
