"""Delete permanently removes a strategy's rows for good; Delete (soft) and Restore keep working.

The fake below behaves like the cloud table: ``delete`` only hides a row (valid = false, still
stored, invisible to reads) and ``purge`` removes it. The older fakes in test_draft_strategy_v2
remove on ``delete``, which is why hidden rows were never noticed.
"""

from __future__ import annotations

import copy
import unittest
from unittest import mock

import draft_strategy_store as dss
import draft_strategy_v2 as v2
from draft_state import DRAFT_QUEUE_KEY
from tests.test_draft_strategy_v2 import _v1

TYPES = (v2.ITEM_TYPE, v2.BACKUP_ITEM_TYPE, v2.RESEARCH_ITEM_TYPE, v2.TRASH_ITEM_TYPE)


class _CloudLike:
    """Rows keep a ``valid`` flag like ``suite_saved_items``."""

    def __init__(self) -> None:
        self.stored: dict[str, dict] = {}  # key -> {"payload", "valid"}
        self.purged: list[tuple[str, bool]] = []

    def put(self, key, title, payload):
        self.stored[key] = {"payload": copy.deepcopy(payload), "valid": True}

    def all(self):
        return [copy.deepcopy(r["payload"]) for r in self.stored.values() if r["valid"]]

    def fetch(self, key):
        r = self.stored.get(key)
        return copy.deepcopy(r["payload"]) if r and r["valid"] else None

    def delete(self, key):  # invalidate_saved_item: hide, keep the data
        if key in self.stored:
            self.stored[key]["valid"] = False

    def purge(self, key, *, only_hidden=False):  # delete_saved_item
        self.purged.append((key, only_hidden))
        r = self.stored.get(key)
        if r is None or (only_hidden and r["valid"]):
            return 0
        del self.stored[key]
        return 1


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.b = {t: _CloudLike() for t in TYPES}
        for p in (mock.patch("draft_strategy_store._backend", side_effect=lambda t=v2.ITEM_TYPE: self.b[t]),
                  mock.patch("suite_auth.is_auth_enabled", return_value=False)):
            p.start()
            self.addCleanup(p.stop)
        self.b[v2.ITEM_TYPE].put("A", "Alpha", _v1("A", "Alpha", [("Aaron Judge", "power"), ("Juan Soto", "")]))
        self.b[v2.ITEM_TYPE].put("B", "Bravo", _v1("B", "Bravo", [("Kyle Tucker", "")]))
        self.s = {DRAFT_QUEUE_KEY: ["Global One"], "draft_queue_plan": {"pins": [], "notes": {}, "moves": []}}

    def keys_anywhere(self, strategy_id: str) -> dict[str, list[str]]:
        """Every stored row (hidden or not) that belongs to this strategy, per item type."""
        out = {}
        for t, backend in self.b.items():
            keys = [k for k in backend.stored if k == strategy_id or k.startswith(f"{strategy_id}~")]
            if keys:
                out[t] = keys
        return out


class PermanentDeleteTests(_Base):
    def test_delete_permanently_leaves_nothing_stored(self) -> None:
        v2.save_strategy_v2(self.s, v2.remove(v2.get_strategy_v2(self.s, "A"), "Juan Soto"), 0)  # v1 backup
        v2.append_research(self.s, "A", "Judge: elite power")
        row = v2.soft_delete(self.s, "A", confirmed=True)
        self.assertFalse(self.b[v2.ITEM_TYPE].stored["A"]["valid"], "soft delete hides the live row")
        v2.permanent_delete(self.s, row["trash_id"], confirmed=True)
        self.assertEqual(self.keys_anywhere("A"), {}, "no hidden copy of A may remain anywhere")
        self.assertEqual(self.b[v2.ITEM_TYPE].stored["B"]["valid"], True)
        self.assertEqual([s["id"] for s in dss.list_strategies(self.s)], ["B"])

    def test_the_live_row_is_only_removed_while_hidden(self) -> None:
        row = v2.soft_delete(self.s, "A", confirmed=True)
        v2.permanent_delete(self.s, row["trash_id"], confirmed=True)
        self.assertIn(("A", True), self.b[v2.ITEM_TYPE].purged, "live key purged with only_hidden")
        self.assertNotIn(("A", False), self.b[v2.ITEM_TYPE].purged)

    def test_a_live_strategy_with_the_same_id_is_never_touched(self) -> None:
        """Restore Original keeps the previous version in the trash under the live strategy's id."""
        s = v2.get_strategy_v2(self.s, "A")
        edited = v2.save_strategy_v2(self.s, v2.remove(s, "Juan Soto"), 0)
        v2.append_research(self.s, "A", "keep me")
        v2.restore_original_version(self.s, "A", confirmed=True, base_revision=edited["revision"],
                                    base_updated_at=edited["updated_at"])
        (kept,) = v2.list_trash(self.s)
        v2.permanent_delete(self.s, kept["trash_id"], confirmed=True)
        self.assertTrue(self.b[v2.ITEM_TYPE].stored["A"]["valid"])
        self.assertIn("A", self.b[v2.RESEARCH_ITEM_TYPE].stored, "the live strategy keeps its research")
        self.assertEqual(self.b[v2.TRASH_ITEM_TYPE].stored, {})

    def test_another_deleted_copy_keeps_its_research(self) -> None:
        v2.append_research(self.s, "A", "shared research")
        first = v2.soft_delete(self.s, "A", confirmed=True)
        v2.restore_from_trash(self.s, first["trash_id"])
        with mock.patch("draft_strategy_store._now", return_value="2099-01-01T00:00:00+00:00"):
            second = v2.soft_delete(self.s, "A", confirmed=True)
        # an older trash copy is still listed (restore hid it); add one more live copy in trash
        self.b[v2.TRASH_ITEM_TYPE].put(first["trash_id"], "Alpha", first)
        v2.permanent_delete(self.s, second["trash_id"], confirmed=True)
        self.assertIn("A", self.b[v2.RESEARCH_ITEM_TYPE].stored, "still needed by the other deleted copy")
        self.assertIn(first["trash_id"], self.b[v2.TRASH_ITEM_TYPE].stored)

    def test_expiry_after_30_days_removes_for_good(self) -> None:
        v2.append_research(self.s, "B", "speed")
        with mock.patch("draft_strategy_store._now", return_value="2026-10-01T10:00:00+00:00"):
            v2.soft_delete(self.s, "B", confirmed=True)
        self.assertEqual(v2.list_trash(self.s, now="2026-11-01T10:00:00+00:00"), [])
        self.assertEqual(self.keys_anywhere("B"), {})
        self.assertTrue(self.b[v2.ITEM_TYPE].stored["A"]["valid"])

    def test_soft_delete_and_restore_still_recover_everything(self) -> None:
        v2.append_research(self.s, "A", "note")
        row = v2.soft_delete(self.s, "A", confirmed=True)
        restored = v2.restore_from_trash(self.s, row["trash_id"])
        self.assertEqual(restored["id"], "A")
        self.assertTrue(self.b[v2.ITEM_TYPE].stored["A"]["valid"])
        self.assertIn("A", self.b[v2.RESEARCH_ITEM_TYPE].stored)
        self.assertEqual(self.b[v2.ITEM_TYPE].purged, [], "nothing is removed for good by soft delete/restore")

    def test_confirmation_and_the_pause_switch_still_apply(self) -> None:
        row = v2.soft_delete(self.s, "A", confirmed=True)
        with self.assertRaises(dss.StrategyError):
            v2.permanent_delete(self.s, row["trash_id"], confirmed=False)
        with mock.patch("strategy_deletion_guard.DELETION_PAUSED", True), self.assertRaises(dss.StrategyError):
            v2.permanent_delete(self.s, row["trash_id"], confirmed=True)
        self.assertIn(row["trash_id"], self.b[v2.TRASH_ITEM_TYPE].stored)
        self.assertEqual(self.b[v2.TRASH_ITEM_TYPE].purged, [])


class StorageDeleteTests(unittest.TestCase):
    def setUp(self) -> None:
        import suite_storage_supabase as sss

        self.sss = sss
        for p in (mock.patch.object(sss, "_scoped_user_id", return_value="user-1"),
                  mock.patch.object(sss, "_scoped_storage_app", side_effect=lambda a: f"{a}__ws")):
            p.start()
            self.addCleanup(p.stop)

    def test_delete_is_scoped_to_the_account_and_the_one_item(self) -> None:
        with mock.patch.object(self.sss, "_request", return_value=[{"id": 9}]) as req:
            n = self.sss.delete_saved_item("baseball", "draft_strategy_trash", "A~2026")
        self.assertEqual(n, 1)
        args, kwargs = req.call_args
        self.assertEqual(args[:2], ("DELETE", self.sss._TABLE_SAVED))
        self.assertEqual(kwargs["params"], {"user_id": "eq.user-1", "app": "eq.baseball__ws",
                                            "item_type": "eq.draft_strategy_trash", "item_key": "eq.A~2026"})

    def test_only_hidden_never_matches_a_live_row(self) -> None:
        with mock.patch.object(self.sss, "_request", return_value=[]) as req:
            self.assertEqual(self.sss.delete_saved_item("baseball", "draft_strategy", "A", only_hidden=True), 0)
        self.assertEqual(req.call_args.kwargs["params"]["valid"], "eq.false")

    def test_guests_and_empty_keys_send_nothing(self) -> None:
        with mock.patch.object(self.sss, "_request") as req:
            self.assertEqual(self.sss.delete_saved_item("baseball", "draft_strategy", ""), 0)
        req.assert_not_called()
        with mock.patch.object(self.sss, "_scoped_user_id", side_effect=RuntimeError("Sign in")), \
                mock.patch.object(self.sss, "_request") as req, self.assertRaises(RuntimeError):
            self.sss.delete_saved_item("baseball", "draft_strategy", "A")
        req.assert_not_called()

    def test_the_pause_switch_refuses_strategy_deletes(self) -> None:
        with mock.patch("strategy_deletion_guard.DELETION_PAUSED", True), \
                mock.patch.object(self.sss, "_request") as req, self.assertRaises(Exception):
            self.sss.delete_saved_item("baseball", "draft_strategy", "A")
        req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
