"""Draft board cloud save: result API, four-pick readback, and refused writes."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import suite_cloud_state as scs


def four_pick_state() -> dict:
    return {
        "draft_room_table": {
            "table_records": [
                {"Round": 1, "Pick": n, "Team": "NYY", "Player": f"Player {n}"}
                for n in range(1, 5)
            ]
        }
    }


def two_pick_state() -> dict:
    state = four_pick_state()
    state["draft_room_table"]["table_records"] = state["draft_room_table"]["table_records"][:2]
    return state


SECRET = (
    "POST https://abc.supabase.co/rest/v1/suite_app_current_state "
    "apikey=sb_live_secret eyJhbGciOiJIUzI1NiJ9.abc.def"
)


class FakeStore:
    def __init__(self, blob=None, updated_at="2026-10-27T10:00:00+00:00"):
        self.blob = blob
        self.updated_at = updated_at
        self.fail = False
        self.fail_message = SECRET
        self.writes: list[dict] = []
        self.app_keys: list[str] = []

    def normalize_app_key(self, key):
        return key

    def load_current_state_meta_for_app(self, app_id):
        if self.fail:
            raise ConnectionError(self.fail_message)
        if self.blob is None:
            return {}
        return {"updated_at": self.updated_at}

    def load_current_state_for_app(self, app_id):
        if self.fail:
            raise ConnectionError(self.fail_message)
        if self.blob is None:
            return None
        return {"updated_at": self.updated_at, "metrics": {scs.FULL_SESSION_KEY: self.blob}}

    def save_current_state(self, app_key, *, page, summary, metrics, skip_metrics_merge_read=False):
        if self.fail:
            raise ConnectionError(self.fail_message)
        self.app_keys.append(app_key)
        written = metrics[scs.FULL_SESSION_KEY]
        self.writes.append(written)
        self.blob = written
        self.updated_at = "2026-10-27T12:00:00+00:00"


class DraftBoardCloudSaveResultTests(unittest.TestCase):
    def _patches(self, store: FakeStore, session: dict, *, guest: bool = False, app_key: str = "baseball"):
        return (
            patch("suite_storage_config.cloud_storage_enabled", return_value=True),
            patch.object(scs, "_import_storage", return_value=(store, "fake")),
            patch.object(scs, "_streamlit_session", return_value=session),
            patch.object(scs, "_anonymous_guest", return_value=guest),
            patch.object(scs, "_cloud_storage_app_id", return_value=app_key),
        )

    def test_import_resolves(self) -> None:
        from draft_room_state import save_draft_board_direct_to_cloud

        self.assertTrue(callable(scs.save_cloud_full_session_with_result))
        self.assertTrue(callable(scs.save_cloud_full_session_with_details))
        self.assertTrue(callable(scs.verify_cloud_draft_room_readback))
        self.assertTrue(callable(save_draft_board_direct_to_cloud))

    def test_successful_save_readback_confirms_four_picks(self) -> None:
        store = FakeStore(None)
        session: dict = {}
        state = four_pick_state()
        patches = self._patches(store, session)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            ok, err = scs.save_cloud_full_session_with_result(
                "baseball",
                state,
                page="Draft Room Simulator",
                summary="four picks",
                min_draft_pick_count=4,
            )
            readback = scs.verify_cloud_draft_room_readback("baseball", min_picks=4, session=session)
        self.assertTrue(ok, err)
        self.assertEqual(err, "")
        self.assertEqual(len(store.writes), 1)
        self.assertEqual(readback["pick_count"], 4)
        self.assertTrue(readback["ok"])
        self.assertEqual(session["_suite_last_draft_room_readback"]["pick_count"], 4)
        self.assertEqual(store.app_keys, ["baseball"])

    def test_failed_save_redacts_credentials_and_does_not_write(self) -> None:
        store = FakeStore(four_pick_state())
        store.fail = True
        session: dict = {}
        patches = self._patches(store, session)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            ok, err = scs.save_cloud_full_session_with_result("baseball", {"active_page": "Home"})
            shown = scs.cloud_write_error_message(session)
        self.assertFalse(ok)
        self.assertEqual(store.writes, [])
        self.assertEqual(store.blob["draft_room_table"]["table_records"].__len__(), 4)
        for text in (err, shown):
            self.assertNotIn("supabase.co", text)
            self.assertNotIn("sb_live_secret", text)
            self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", text)
            self.assertIn("<cloud>", text)
            self.assertIn("<key>", text)

    def test_short_board_is_refused_before_write(self) -> None:
        store = FakeStore(four_pick_state())
        session: dict = {}
        patches = self._patches(store, session)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            ok, err = scs.save_cloud_full_session_with_result(
                "baseball",
                two_pick_state(),
                min_draft_pick_count=4,
            )
        self.assertFalse(ok)
        self.assertIn("draft_pick_count_below_minimum", err)
        self.assertIn("expected=4", err)
        self.assertIn("got=2", err)
        self.assertEqual(store.writes, [])
        self.assertEqual(len(store.blob["draft_room_table"]["table_records"]), 4)

    def test_unresolved_read_failure_does_not_overwrite_stored_board(self) -> None:
        stored = four_pick_state()
        store = FakeStore(stored)
        session = {
            scs.CLOUD_READ_FAILED_KEY: {
                "app_id": "baseball",
                "error": "ConnectionError",
                "count": 1,
                "at": 1,
            }
        }
        patches = self._patches(store, session)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            ok, err = scs.save_cloud_full_session_with_result(
                "baseball",
                four_pick_state(),
                min_draft_pick_count=4,
            )
        self.assertFalse(ok)
        self.assertIn("could not be read", err)
        self.assertEqual(store.writes, [])
        self.assertEqual(store.blob, stored)

    def test_anonymous_guest_cannot_write(self) -> None:
        store = FakeStore(four_pick_state())
        session: dict = {}
        patches = self._patches(store, session, guest=True)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            ok, err = scs.save_cloud_full_session_with_result(
                "baseball",
                four_pick_state(),
                min_draft_pick_count=4,
            )
        self.assertFalse(ok)
        self.assertIn("sign in", err)
        self.assertEqual(store.writes, [])

    def test_write_uses_scoped_app_key(self) -> None:
        store = FakeStore(None)
        session: dict = {}
        patches = self._patches(store, session, app_key="baseball__ariel")
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            ok, err = scs.save_cloud_full_session_with_result(
                "baseball",
                four_pick_state(),
                min_draft_pick_count=4,
            )
        self.assertTrue(ok, err)
        self.assertEqual(store.app_keys, ["baseball__ariel"])

    def test_newer_cloud_timestamp_blocks_direct_save(self) -> None:
        self.assertFalse(
            scs.cloud_write_blocked_by_newer_data(
                "2026-10-27T10:00:00+00:00",
                "2026-10-27T10:00:00+00:00",
            )
        )
        self.assertTrue(
            scs.cloud_write_blocked_by_newer_data(
                "2026-10-27T10:00:00+00:00",
                "2026-10-27T11:00:00+00:00",
            )
        )
        from draft_room_state import save_draft_board_direct_to_cloud

        session = four_pick_state()
        st = SimpleNamespace(session_state=session)
        loads = [
            (dict(session), "2026-10-27T10:00:00+00:00"),
            (dict(session), "2026-10-27T11:00:00+00:00"),
        ]

        def _load(app_id, force=False):
            return loads.pop(0)

        with (
            patch("suite_storage_config.cloud_storage_enabled", return_value=True),
            patch(
                "suite_workspace.workspace_persistence_meta",
                return_value={"active_workspace_id": "daniel", "cloud_app_key": "baseball"},
            ),
            patch("baseball_persistent_state.build_baseball_disk_state", return_value=dict(session)),
            patch("suite_cloud_state.load_cloud_full_session", side_effect=_load),
            patch("suite_cloud_state.cloud_read_failure", return_value=None),
            patch("suite_cloud_state.save_cloud_full_session_with_result") as saver,
        ):
            trace = save_draft_board_direct_to_cloud(st, session)
        saver.assert_not_called()
        self.assertFalse(trace["saved_cloud"])
        self.assertEqual(trace["error"], "cloud_newer_than_loaded_session")
        self.assertEqual(
            session[scs.CLOUD_READ_FAILED_KEY]["error"],
            "RuntimeError",
        )
        self.assertEqual(
            session[scs.CLOUD_WRITE_BLOCKED_KEY]["reason"],
            "cloud_newer_than_loaded_session",
        )

    def test_direct_save_exception_is_redacted(self) -> None:
        from draft_room_state import record_manual_save_error, save_draft_board_direct_to_cloud

        session: dict = {}
        st = SimpleNamespace(session_state=session)
        with (
            patch("suite_storage_config.cloud_storage_enabled", return_value=True),
            patch("suite_workspace.workspace_persistence_meta", side_effect=RuntimeError(SECRET)),
        ):
            trace = save_draft_board_direct_to_cloud(st, session)
        self.assertFalse(trace["saved_cloud"])
        self.assertNotIn("supabase.co", trace["error"])
        self.assertNotIn("sb_live_secret", trace["cloud_write_error"])
        self.assertIn("<cloud>", trace["error"])
        self.assertIn("<key>", trace["error"])
        record_manual_save_error(session, RuntimeError(SECRET))
        shown = session["_draft_room_manual_save_result"]["error"]
        self.assertNotIn("https://", shown)
        self.assertNotIn("sb_live_secret", shown)


if __name__ == "__main__":
    unittest.main()
