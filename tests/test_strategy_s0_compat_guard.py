"""Slice 0 compatibility release: the strategy-deletion pause and reading what Slice 2 writes.

Deletion guard (owner, 2026-11-08): until Slice 2's recoverable deletion is live no saved Draft
Strategy may be removed. The page shows a disabled Delete button with the pause message, and the
store, both storage backends and the Supabase saved-item call refuse as well. Viewing, editing and
saving keep working.

Compatibility: tests/fixtures/s2_written_strategies.json was written by the Slice 2 store's own
code (feature/pro-strategy-queues @ 55dd6f3): an untouched v1 strategy, a 251-player v2 strategy
with player ids, a note, a pin, an edit and a research entry, and a soft-deleted strategy (its own
trash file). Slice 0's reader must show both live strategies in full and never the deleted one.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import draft_strategy_store as dss
import strategy_deletion_guard as guard
from draft_state import DRAFT_QUEUE_KEY

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "s2_written_strategies.json").read_text(encoding="utf-8")
)["files"]
BIG_ID = next(k for k, v in FIXTURE["draft_strategies.json"].items() if v.get("name") == "Big")
LEGACY_ID = next(k for k, v in FIXTURE["draft_strategies.json"].items() if v.get("name") == "Legacy v1")


class _Workspace:
    """A temporary local workspace holding the Slice 2 files; Slice 0's local backend reads it."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        for name, data in FIXTURE.items():
            (root / name).write_text(json.dumps(data), encoding="utf-8")
        self.path = root / "draft_strategies.json"
        self.root = root
        self._patches = [
            mock.patch("draft_strategy_store._LocalBackend._path", lambda _self: self.path),
            mock.patch("suite_storage_config.cloud_storage_enabled", return_value=False),
            mock.patch("suite_auth.is_auth_enabled", return_value=False),
        ]
        for p in self._patches:
            p.start()
        return self

    def raw(self, name: str = "draft_strategies.json") -> dict:
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()


class DeletionGuardTests(unittest.TestCase):
    def test_the_pause_is_on_with_the_owners_message(self) -> None:
        self.assertTrue(guard.DELETION_PAUSED)
        self.assertEqual(guard.PAUSED_MESSAGE,
                         "Deleting strategies is temporarily paused while recoverable deletion is being introduced.")

    def test_the_store_refuses_even_when_confirmed(self) -> None:
        with _Workspace() as ws:
            before = ws.raw()
            with self.assertRaises(dss.StrategyError) as err:
                dss.delete_strategy({}, BIG_ID, confirmed=True)
            self.assertEqual(str(err.exception), guard.PAUSED_MESSAGE)
            self.assertEqual(ws.raw(), before)  # the file is untouched

    def test_the_local_backend_refuses_directly(self) -> None:
        with _Workspace() as ws:
            before = ws.raw()
            with self.assertRaises(guard.StrategyDeletionPaused):
                dss._LocalBackend().delete(BIG_ID)
            self.assertEqual(ws.raw(), before)

    def test_the_cloud_backend_refuses_before_any_request(self) -> None:
        with mock.patch("suite_storage_supabase._request") as request:
            with self.assertRaises(guard.StrategyDeletionPaused):
                dss._CloudBackend().delete(BIG_ID)
        request.assert_not_called()

    def test_the_supabase_saved_item_call_refuses_strategies_only(self) -> None:
        import suite_storage_supabase as sss

        with mock.patch("suite_storage_supabase._request") as request:
            with self.assertRaises(guard.StrategyDeletionPaused):
                sss.invalidate_saved_item("baseball", "draft_strategy", BIG_ID)
            request.assert_not_called()
            with mock.patch("suite_storage_supabase._scoped_storage_app", return_value="baseball"), \
                    mock.patch("suite_storage_supabase._scoped_user_id", return_value="u1"):
                sss.invalidate_saved_item("baseball", "player", "aaron-judge")  # other items unaffected
            request.assert_called_once()

    def test_viewing_editing_and_saving_still_work(self) -> None:
        with _Workspace() as ws:
            session = {DRAFT_QUEUE_KEY: []}
            with mock.patch("draft_strategy_store._require_access"):
                renamed = dss.rename_strategy(session, LEGACY_ID, "Legacy renamed")
                session[DRAFT_QUEUE_KEY] = ["Gunnar Henderson", "Bobby Witt Jr.", "Juan Soto"]
                dss.update_strategy(session, LEGACY_ID, confirm_overwrite=True)
                saved = dss.save_strategy(session, "Fresh", approach="balanced")
            names = sorted(s["name"] for s in dss.list_strategies(session))
            self.assertEqual(names, ["Big", "Fresh", "Legacy renamed"])
            self.assertEqual(renamed["name"], "Legacy renamed")
            self.assertEqual([p["name"] for p in dss.get_strategy(session, LEGACY_ID)["players"]],
                             ["Gunnar Henderson", "Bobby Witt Jr.", "Juan Soto"])
            self.assertIn(saved["id"], ws.raw())

    def test_the_page_shows_a_disabled_delete_button_and_the_message(self) -> None:
        from streamlit.testing.v1 import AppTest

        def page() -> None:
            from unittest import mock

            import streamlit as st

            import draft_strategy_ui as dsu

            strategy = {"schema_version": 1, "id": "s1", "name": "Power bats", "approach": "balanced",
                        "players": [{"name": "Aaron Judge", "rank": 1, "note": ""}], "explanations": [],
                        "context": {}, "created_at": "2026-11-01", "updated_at": "2026-11-01"}
            with mock.patch("draft_strategy_ui._persist"), mock.patch("draft_strategy_ui._flash"):
                dsu._render_strategy(st, st.session_state, strategy, ["Aaron Judge"])

        at = AppTest.from_function(page, default_timeout=30)
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        delete = [b for b in at.button if b.key == "strategy_s1_delete_btn"]
        self.assertEqual(len(delete), 1)
        self.assertTrue(delete[0].disabled)
        self.assertTrue(any(guard.PAUSED_MESSAGE in c.value for c in at.caption))


class SliceTwoFormatTests(unittest.TestCase):
    """Slice 0 (the rollback floor) reading what Slice 2 writes."""

    def test_the_251_player_strategy_lists_and_loads_in_full(self) -> None:
        with _Workspace():
            session = {DRAFT_QUEUE_KEY: []}
            listed = {s["name"]: s for s in dss.list_strategies(session)}
            self.assertEqual(sorted(listed), ["Big", "Legacy v1"])  # the deleted one stays hidden
            self.assertEqual(len(listed["Big"]["players"]), 251)
            with mock.patch("draft_strategy_store._require_access"):
                dss.load_strategy(session, BIG_ID, confirm_replace=True)
            queue = session[DRAFT_QUEUE_KEY]
            self.assertEqual(len(queue), 251)
            self.assertEqual(queue[0], "Aaron Judge")  # Slice 2's reorder is kept
            self.assertEqual(session[dss.LOADED_KEY]["notes"], {"Aaron Judge": "power"})

    def test_the_v1_strategy_keeps_its_queue_order_and_notes(self) -> None:
        with _Workspace():
            session = {DRAFT_QUEUE_KEY: []}
            with mock.patch("draft_strategy_store._require_access"):
                dss.load_strategy(session, LEGACY_ID, confirm_replace=True)
            self.assertEqual(session[DRAFT_QUEUE_KEY], ["Bobby Witt Jr.", "Gunnar Henderson"])
            self.assertEqual(session[dss.LOADED_KEY]["notes"], {"Bobby Witt Jr.": "speed"})

    def test_the_cloud_path_reads_the_same_rows(self) -> None:
        rows = [{"payload": copy.deepcopy(v)} for v in FIXTURE["draft_strategies.json"].values()]
        with mock.patch("suite_storage_config.cloud_storage_enabled", return_value=True), \
                mock.patch("suite_storage_supabase.load_saved_items", return_value=rows) as load:
            listed = {s["name"]: s for s in dss.list_strategies({})}
        self.assertEqual(load.call_args.kwargs.get("item_type"), "draft_strategy")  # never the trash type
        self.assertEqual(sorted(listed), ["Big", "Legacy v1"])
        self.assertEqual(len(listed["Big"]["players"]), 251)

    def test_editing_a_slice_two_strategy_on_slice_zero_keeps_its_slice_two_fields(self) -> None:
        with _Workspace() as ws:
            before = ws.raw()[BIG_ID]
            session = {DRAFT_QUEUE_KEY: ["Juan Soto", "Aaron Judge"]}
            with mock.patch("draft_strategy_store._require_access"):
                dss.rename_strategy(session, BIG_ID, "Big bats")
                dss.update_strategy(session, BIG_ID, confirm_overwrite=True)
            after = ws.raw()[BIG_ID]
            for field in set(before) - {"players", "context", "updated_at", "name"}:
                self.assertEqual(after[field], before[field], field)  # ids, notes, pins, revision, edits
            self.assertEqual([p["name"] for p in after["players"]], ["Juan Soto", "Aaron Judge"])
            self.assertNotEqual(after["updated_at"], before["updated_at"])  # Slice 2 sees the change
            self.assertEqual(ws.raw("draft_strategy_trash.json"), FIXTURE["draft_strategy_trash.json"])
            self.assertEqual(ws.raw("draft_strategy_research.json"), FIXTURE["draft_strategy_research.json"])


if __name__ == "__main__":
    unittest.main()
