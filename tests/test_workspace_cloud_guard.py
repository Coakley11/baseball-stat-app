"""Cloud full-session writes must not erase a verified board or a richer workspace."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

import suite_cloud_state as scs
import suite_user_persistence as sup
from workspace_cloud_guard import (
    VERIFIED_BOARD_SNAPSHOT_KEY,
    authorize_explicit_reset,
    filled_pick_count,
    note_cloud_revision_seen,
    recover_board_from_verified_snapshot,
)

APP = "baseball"
TS = "2026-10-28T01:22:30"
NEWER = "2026-10-28T03:48:58"


def _board(n: int, **extra) -> dict:
    records = [
        {"Round": 1, "Pick": i + 1, "Team": "A", "Player": f"Player {i + 1}"}
        for i in range(n)
    ]
    blob = {
        "_persist_schema": 1,
        "table_records": records,
        "table_columns": ["Round", "Pick", "Team", "Player"],
        "pick_count": n,
    }
    state = {
        "draft_room_state": blob,
        "draft_room_table": dict(blob),
        "active_page": "Draft Room Simulator",
        "draft_archive_teams": [{"draft_id": "saved-1", "name": "Saved"}],
        "fantasy_league_context_state": {"active_league_context_id": "lg-1", "contexts": [{"id": "lg-1"}]},
        "draft_queue": {"players": ["queued"]},
        "watchlist_favorites": ["Aaron Judge"],
        "fantasy_research_mode_selection": "verified",
    }
    state.update(extra)
    return state


class Store:
    def __init__(self, blob=None, updated_at=TS, snapshot=None):
        self.blob = blob
        self.updated_at = updated_at
        self.snapshot = snapshot
        self.fail = False
        self.writes: list[dict] = []
        self.app_keys: list[str] = []

    def normalize_app_key(self, key):
        return key

    def load_current_state_meta_for_app(self, app_id):
        if self.fail:
            raise ConnectionError("store unreachable")
        if self.blob is None and not self.updated_at:
            return {}
        return {"updated_at": self.updated_at}

    def load_current_state_for_app(self, app_id):
        if self.fail:
            raise ConnectionError("store unreachable")
        if self.blob is None and self.snapshot is None:
            return None
        metrics = {}
        if self.blob is not None:
            metrics[scs.FULL_SESSION_KEY] = self.blob
        if self.snapshot is not None:
            metrics[VERIFIED_BOARD_SNAPSHOT_KEY] = self.snapshot
        return {"updated_at": self.updated_at, "metrics": metrics}

    def save_current_state(self, app_key, *, page, summary, metrics, skip_metrics_merge_read=False, expected_updated_at=None):
        if expected_updated_at is not None and str(expected_updated_at or "")[:19] != str(self.updated_at or "")[:19]:
            return False
        self.app_keys.append(app_key)
        written = metrics[scs.FULL_SESSION_KEY]
        self.writes.append(written)
        self.blob = written
        if VERIFIED_BOARD_SNAPSHOT_KEY in metrics:
            self.snapshot = metrics[VERIFIED_BOARD_SNAPSHOT_KEY]
        self.updated_at = NEWER
        return True


class GuardTests(unittest.TestCase):
    def _run(self, store: Store, session: dict, state: dict, reason: str = "fantasy_edit", guest: bool = False):
        st = SimpleNamespace(session_state=session, warning=mock.Mock(), success=mock.Mock(), toast=mock.Mock())
        with (
            mock.patch("suite_storage_config.cloud_storage_enabled", return_value=True),
            mock.patch.object(scs, "_import_storage", return_value=(store, "fake")),
            mock.patch.object(scs, "_streamlit_session", return_value=session),
            mock.patch.object(scs, "_anonymous_guest", return_value=guest),
            mock.patch.object(scs, "_cloud_storage_app_id", return_value="baseball"),
            mock.patch.object(scs, "invalidate_cloud_full_session_cache", lambda app_id: None),
        ):
            ok = scs.save_cloud_full_session(APP, state, page="Trend Value", summary="edit", save_reason=reason)
        return ok, st

    def test_four_picks_restore_on_refresh_signin_and_restart(self):
        store = Store(_board(4))
        for _label in ("refresh", "sign-in", "restart"):
            session: dict = {}
            st = SimpleNamespace(session_state=session)
            with (
                mock.patch("suite_storage_config.cloud_storage_enabled", return_value=True),
                mock.patch.object(scs, "_import_storage", return_value=(store, "fake")),
                mock.patch.object(scs, "_streamlit_session", return_value=session),
                mock.patch.object(scs, "_anonymous_guest", return_value=False),
                mock.patch.object(sup, "_load_raw", return_value=({}, None, None)),
                mock.patch.object(sup, "save_user_state", return_value=True),
                mock.patch("suite_egress_policy.cloud_autosave_allowed", return_value=(True, "")),
            ):
                applied = []
                ok = sup.sync_workspace_protocol(st, APP, apply_state=lambda _st, state: applied.append(state))
            self.assertTrue(ok)
            self.assertEqual(filled_pick_count(applied[-1]), 4)
            self.assertEqual(session["_suite_cloud_revision_seen"], TS)

    def test_auth_not_ready_does_not_confirm_empty_or_write(self):
        store = Store(_board(4))
        session: dict = {}
        st = SimpleNamespace(session_state=session, warning=mock.Mock())
        with (
            mock.patch("suite_storage_config.cloud_storage_enabled", return_value=True),
            mock.patch.object(scs, "_import_storage", return_value=(store, "fake")),
            mock.patch.object(scs, "_streamlit_session", return_value=session),
            mock.patch.object(scs, "_anonymous_guest", return_value=True),
            mock.patch.object(sup, "_load_raw", return_value=({}, None, None)),
        ):
            self.assertEqual(scs.load_cloud_full_session_status(APP, force=True).status, scs.CLOUD_READ_NOT_READY)
            self.assertFalse(sup.sync_workspace_protocol(st, APP, apply_state=lambda *_a: None))
        self.assertNotIn(scs.CLOUD_RECONCILED_KEY, session)
        self.assertIn("auth not ready", session["_suite_persist_restore_skip_reason"])
        ok, _st = self._run(store, session, {"active_page": "Trend Value"}, guest=True)
        self.assertFalse(ok)
        self.assertEqual(store.writes, [])
        self.assertEqual(filled_pick_count(store.blob), 4)

    def test_failed_read_cannot_authorize_a_write(self):
        store = Store(_board(4))
        store.fail = True
        session: dict = {}
        ok, _st = self._run(store, session, {"active_page": "Trend Value"})
        self.assertFalse(ok)
        self.assertEqual(store.writes, [])

    def test_fantasy_edit_and_page_change_cannot_zero_a_verified_board(self):
        for reason in ("fantasy_edit", "page_change", "historical_edit", "trend_edit", "autosave"):
            store = Store(_board(4))
            session: dict = {}
            note_cloud_revision_seen(session, TS)
            ok, _st = self._run(store, session, {"active_page": "Trend Value", "trend_players_multi": ["A"]}, reason=reason)
            self.assertTrue(ok, reason)
            self.assertEqual(filled_pick_count(store.blob), 4)
            self.assertEqual(store.blob["draft_archive_teams"][0]["draft_id"], "saved-1")
            self.assertEqual(store.blob["fantasy_league_context_state"]["active_league_context_id"], "lg-1")
            self.assertEqual(store.blob["draft_queue"]["players"], ["queued"])
            self.assertEqual(store.blob["watchlist_favorites"], ["Aaron Judge"])
            self.assertEqual(store.blob["fantasy_research_mode_selection"], "verified")
            self.assertEqual(store.blob["trend_players_multi"], ["A"])
            self.assertFalse(store.snapshot.get("cleared"))
            self.assertEqual(store.snapshot.get("pick_count"), 4)

    def test_explicit_reset_clears_board_and_snapshot(self):
        store = Store(_board(4))
        session: dict = {}
        note_cloud_revision_seen(session, TS)
        authorize_explicit_reset(session, reason="reset_simulator_board")
        ok, _st = self._run(store, session, {"active_page": "Draft Room Simulator"}, reason="reset_simulator_board")
        self.assertTrue(ok)
        self.assertEqual(filled_pick_count(store.blob), 0)
        self.assertTrue(store.snapshot.get("cleared"))
        self.assertEqual(store.snapshot.get("reason"), "reset_simulator_board")
        self.assertEqual(store.snapshot.get("previous_verified", {}).get("pick_count"), 4)

    def test_undo_can_reduce_picks_without_clearing_recovery_snapshot(self):
        store = Store(_board(4), snapshot={"schema": 1, "pick_count": 4, "cleared": False, "draft_room_state": {"pick_count": 4}})
        session: dict = {}
        note_cloud_revision_seen(session, TS)
        ok, _st = self._run(store, session, _board(3), reason="undo_last_pick")
        self.assertTrue(ok)
        self.assertEqual(filled_pick_count(store.blob), 3)
        self.assertFalse(store.snapshot.get("cleared"))
        self.assertEqual(store.snapshot.get("pick_count"), 3)

    def test_new_empty_draft_is_allowed_when_cloud_is_empty(self):
        store = Store(None, updated_at="")
        session: dict = {}
        note_cloud_revision_seen(session, "", confirmed_empty=True)
        ok, _st = self._run(store, session, {"active_page": "Draft Room Simulator"}, reason="manual_save")
        self.assertTrue(ok)
        self.assertEqual(store.writes[-1]["active_page"], "Draft Room Simulator")

    def test_stale_session_cannot_overwrite_newer_cloud_data(self):
        store = Store(_board(5), updated_at=NEWER)
        session: dict = {}
        note_cloud_revision_seen(session, TS)
        ok, _st = self._run(store, session, _board(4), reason="manual_save")
        self.assertFalse(ok)
        self.assertEqual(store.writes, [])
        self.assertEqual(filled_pick_count(store.blob), 5)
        self.assertEqual(session[scs.CLOUD_WRITE_BLOCKED_KEY]["reason"], "stale_or_unhydrated_cloud_revision")

    def test_unhydrated_session_cannot_replace_a_richer_row(self):
        store = Store(_board(4))
        session: dict = {}
        ok, _st = self._run(store, session, {"active_page": "Trend Value"}, reason="fantasy_edit")
        self.assertFalse(ok)
        self.assertEqual(filled_pick_count(store.blob), 4)
        self.assertEqual(store.writes, [])

    def test_scoped_key_is_unchanged_and_other_account_row_is_not_written(self):
        store = Store(None, updated_at="")
        session: dict = {}
        note_cloud_revision_seen(session, "", confirmed_empty=True)
        with (
            mock.patch("suite_storage_config.cloud_storage_enabled", return_value=True),
            mock.patch.object(scs, "_import_storage", return_value=(store, "fake")),
            mock.patch.object(scs, "_streamlit_session", return_value=session),
            mock.patch.object(scs, "_anonymous_guest", return_value=False),
            mock.patch.object(scs, "_cloud_storage_app_id", return_value="baseball__coakley11"),
            mock.patch.object(scs, "invalidate_cloud_full_session_cache", lambda app_id: None),
        ):
            ok = scs.save_cloud_full_session(APP, {"active_page": "Home"}, save_reason="manual_save")
        self.assertTrue(ok)
        self.assertEqual(store.app_keys, ["baseball__coakley11"])

    def test_same_second_writers_and_offset_timestamps_do_not_collide(self):
        import suite_storage_supabase as storage

        stored = "2026-10-28T15:50:28.100000+00:00"
        db = {
            "updated_at": stored,
            "metrics": {
                scs.FULL_SESSION_KEY: _board(4),
                VERIFIED_BOARD_SNAPSHOT_KEY: {"schema": 1, "pick_count": 4, "cleared": False},
            },
        }
        calls = []

        def request(method, path, *, params=None, json_body=None, prefer="return=minimal", cfg=None, use_cache=None):
            calls.append((method, params, json_body))
            self.assertEqual(method, "PATCH")
            expected = str((params or {}).get("updated_at") or "")
            self.assertEqual(expected, f"eq.{stored}")
            self.assertIn(".100000+00:00", expected)
            self.assertNotEqual(expected, f"eq.{stored[:19]}")
            if db["updated_at"] != stored:
                return []
            written = str((json_body or {}).get("updated_at") or "")
            self.assertNotEqual(written, stored)
            self.assertIn("+00:00", written)
            self.assertIn(".", written)
            db["updated_at"] = written
            db["metrics"] = (json_body or {}).get("metrics") or db["metrics"]
            return [{"updated_at": written, "metrics": db["metrics"]}]

        def save(label):
            with (
                mock.patch.object(storage, "_logical_active_app", return_value=("baseball", "baseball")),
                mock.patch.object(storage, "_cloud_user_id", return_value="user-1"),
                mock.patch.object(storage, "_request", side_effect=request),
                mock.patch.object(storage, "_merge_state_metrics", side_effect=lambda _key, incoming, allow_network=True: {
                    **db["metrics"],
                    **dict(incoming or {}),
                    VERIFIED_BOARD_SNAPSHOT_KEY: db["metrics"][VERIFIED_BOARD_SNAPSHOT_KEY],
                }),
            ):
                return storage.save_current_state(
                    "baseball",
                    page="Trend Value",
                    summary=label,
                    metrics={scs.FULL_SESSION_KEY: {"active_page": label}},
                    expected_updated_at=stored,
                )

        self.assertTrue(save("first"))
        self.assertFalse(save("second"))
        self.assertEqual(len(calls), 2)
        self.assertEqual(db["metrics"][VERIFIED_BOARD_SNAPSHOT_KEY]["pick_count"], 4)
        self.assertNotEqual(db["updated_at"], stored)
        self.assertFalse(save("second-again"))

    def test_zero_row_patch_is_not_a_successful_save(self):
        import suite_storage_supabase as storage

        with (
            mock.patch.object(storage, "_logical_active_app", return_value=("baseball", "baseball")),
            mock.patch.object(storage, "_cloud_user_id", return_value="user-1"),
            mock.patch.object(storage, "_request", return_value=[]),
            mock.patch.object(storage, "_merge_state_metrics", side_effect=lambda _key, incoming, allow_network=True: dict(incoming or {})),
        ):
            wrote = storage.save_current_state(
                "baseball",
                page="Trend Value",
                summary="stale",
                metrics={scs.FULL_SESSION_KEY: {"active_page": "Trend Value"}},
                expected_updated_at="2026-10-28T01:22:30.654321+00:00",
            )
        self.assertFalse(wrote)

    def test_atomic_revision_filter_rejects_a_writer_that_loses_the_race(self):
        import suite_storage_supabase as storage

        db = {"updated_at": TS, "metrics": {scs.FULL_SESSION_KEY: _board(4)}}

        def request(method, path, *, params=None, json_body=None, prefer="return=minimal", cfg=None, use_cache=None):
            self.assertEqual(method, "PATCH")
            self.assertNotIn("resolution=merge-duplicates", prefer)
            db["updated_at"] = NEWER
            expected = str((params or {}).get("updated_at") or "").removeprefix("eq.")
            if str(db["updated_at"])[:19] != expected[:19]:
                return []
            db["metrics"] = json_body["metrics"]
            db["updated_at"] = json_body["updated_at"]
            return [dict(db)]

        with (
            mock.patch.object(storage, "_logical_active_app", return_value=("baseball", "baseball")),
            mock.patch.object(storage, "_cloud_user_id", return_value="user-1"),
            mock.patch.object(storage, "_request", side_effect=request),
            mock.patch.object(storage, "_merge_state_metrics", side_effect=lambda _key, incoming, allow_network=True: dict(incoming or {})),
        ):
            wrote = storage.save_current_state(
                "baseball",
                page="Trend Value",
                summary="stale",
                metrics={scs.FULL_SESSION_KEY: {"active_page": "Trend Value"}},
                expected_updated_at=TS,
            )
        self.assertFalse(wrote)
        self.assertEqual(filled_pick_count(db["metrics"][scs.FULL_SESSION_KEY]), 4)
        self.assertEqual(db["updated_at"], NEWER)

    def test_snapshot_survives_failed_hydration_and_can_restore_four_picks(self):
        board = _board(4)
        snapshot = {
            "schema": 1,
            "pick_count": 4,
            "cleared": False,
            "draft_room_state": board["draft_room_state"],
        }
        store = Store(board, snapshot=snapshot)
        session: dict = {}
        st = SimpleNamespace(session_state=session, warning=mock.Mock())
        with (
            mock.patch("suite_storage_config.cloud_storage_enabled", return_value=True),
            mock.patch.object(scs, "_import_storage", return_value=(store, "fake")),
            mock.patch.object(scs, "_streamlit_session", return_value=session),
            mock.patch.object(scs, "_anonymous_guest", return_value=True),
            mock.patch.object(sup, "_load_raw", return_value=({}, None, None)),
        ):
            self.assertFalse(sup.sync_workspace_protocol(st, APP, apply_state=lambda *_a: None))
        ok, _st = self._run(store, session, {"active_page": "Trend Value"}, reason="fantasy_edit", guest=True)
        self.assertFalse(ok)
        self.assertEqual(store.snapshot.get("pick_count"), 4)
        recovered = recover_board_from_verified_snapshot(store.snapshot)
        self.assertEqual(filled_pick_count(recovered), 4)
        self.assertEqual(store.writes, [])

    def test_blocked_cloud_save_is_not_reported_as_success(self):
        store = Store(_board(4))
        session: dict = {}
        st = SimpleNamespace(session_state=session, warning=mock.Mock())
        with (
            mock.patch("suite_storage_config.cloud_storage_enabled", return_value=True),
            mock.patch("suite_user_persistence.save_user_state", return_value=True),
            mock.patch.object(scs, "_import_storage", return_value=(store, "fake")),
            mock.patch.object(scs, "_streamlit_session", return_value=session),
            mock.patch.object(scs, "_anonymous_guest", return_value=False),
            mock.patch.object(scs, "_cloud_storage_app_id", return_value="baseball"),
            mock.patch.object(scs, "invalidate_cloud_full_session_cache", lambda app_id: None),
            mock.patch("suite_egress_policy.cloud_autosave_allowed", return_value=(True, "")),
        ):
            ok = sup.force_autosave(
                st,
                APP,
                build_state=lambda _st: {"active_page": "Trend Value"},
                reason="fantasy_edit",
            )
        self.assertFalse(ok)
        self.assertFalse(session.get("_suite_persist_last_save_cloud"))
        self.assertTrue(session.get("_suite_autosave_cloud_blocked_reason"))
        self.assertEqual(store.writes, [])

    def test_reset_without_intent_does_not_clear_a_verified_board(self):
        store = Store(_board(4))
        session: dict = {}
        note_cloud_revision_seen(session, TS)
        ok, _st = self._run(store, session, {"active_page": "Draft Room Simulator"}, reason="reset_simulator_board")
        self.assertTrue(ok)
        self.assertEqual(filled_pick_count(store.blob), 4)
