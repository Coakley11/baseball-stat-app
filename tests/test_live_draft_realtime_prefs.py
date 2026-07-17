"""Real-time Live Draft transactions + persistent setup preferences."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_shared_state import (
    LocalFileSharedRoomStore,
    preserve_shared_room_timer_authority,
    reset_shared_room_store_for_tests,
)
from draft_state import add_player_to_draft_queue, remove_player_from_draft_queue, sync_draft_queue
from live_draft_rerun_scope import (
    QUEUE_TICK_KEY,
    live_draft_expensive_recompute_required,
    mark_live_draft_queue_tick,
)
from live_draft_timer_authority import (
    TIMER_AUTHORITY_KEY,
    authority_is_active,
    build_authority_lease,
    extract_live_head_fields,
    expired_pick_needs_watchdog,
    try_acquire_timer_authority,
)
from live_draft_setup_mode import (
    SETUP_MODE_SHARED,
    SETUP_MODE_SOLO,
    get_live_draft_setup_mode,
    set_live_draft_setup_mode,
)
from user_page_preferences import (
    PAGE_KEY_LIVE_DRAFT_SETUP,
    apply_live_draft_setup_settings,
    collect_live_draft_setup_settings,
    default_live_draft_setup_settings,
    ensure_live_draft_setup_preferences_loaded,
    get_user_page_preferences,
    preferences_initialized,
    reset_live_draft_setup_to_defaults,
    restore_live_draft_setup_mode_preference,
    save_user_page_preferences,
)


class QueueDoesNotRebuildRecsTests(unittest.TestCase):
    def test_queue_add_marks_queue_tick_and_skips_expensive(self) -> None:
        session = {"draft_queue": []}
        with mock.patch("draft_state._sync_participant_workflow_if_multiplayer") as sync_mp:
            q, added = add_player_to_draft_queue(session, "Aaron Judge")
        self.assertTrue(added)
        self.assertEqual(q, ["Aaron Judge"])
        sync_mp.assert_not_called()
        self.assertTrue(session.get(QUEUE_TICK_KEY))
        self.assertFalse(live_draft_expensive_recompute_required(session))

    def test_queue_remove_skips_participant_sync(self) -> None:
        session = {"draft_queue": ["Aaron Judge", "Juan Soto"]}
        with mock.patch("draft_state.write_canonical_draft_state", wraps=None) as write:
            # Call through sync path via remove.
            with mock.patch("draft_state._sync_participant_workflow_if_multiplayer") as sync_mp:
                q, removed = remove_player_from_draft_queue(session, "Aaron Judge")
            self.assertTrue(removed)
            self.assertEqual(q, ["Juan Soto"])
            sync_mp.assert_not_called()
        _ = write

    def test_sync_draft_queue_default_skips_mp_for_queue_reasons(self) -> None:
        session = {"draft_queue": []}
        with mock.patch(
            "draft_state.write_canonical_draft_state",
            return_value={"queue": ["A"]},
        ) as write:
            sync_draft_queue(session, ["A"], reason="add_to_queue")
        kwargs = write.call_args.kwargs
        self.assertFalse(kwargs.get("sync_participant"))


class TimerAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmp.name))
        reset_shared_room_store_for_tests(self.store)

    def tearDown(self) -> None:
        reset_shared_room_store_for_tests(None)
        self._tmp.cleanup()

    def test_extract_live_head_fields_no_pool(self) -> None:
        doc = {
            "revision": 4,
            "status": "in_progress",
            "updated_at": "t",
            "room": {
                "current_pick_index": 2,
                "timer_deadline": 123.0,
                "pick_order": [
                    {"Team": "A"},
                    {"Team": "B"},
                    {"Team": "C"},
                ],
                "pool_records": [{"x": 1}] * 500,
            },
        }
        head = extract_live_head_fields(doc)
        self.assertEqual(head["room_revision"], 4)
        self.assertEqual(head["current_pick_index"], 2)
        self.assertEqual(head["current_team"], "C")
        self.assertNotIn("pool_records", head)

    def test_watchdog_detects_stalled_deadline(self) -> None:
        room = {"status": "in_progress", "timer_deadline": time.time() - 5}
        self.assertTrue(expired_pick_needs_watchdog({}, room))
        room2 = {"status": "in_progress", "timer_deadline": time.time() + 30}
        self.assertFalse(expired_pick_needs_watchdog({}, room2))

    def test_authority_lease_active(self) -> None:
        session = {"auth_user_id": "user:daniel", "draft_room_participant_id": "user:daniel"}
        lease = build_authority_lease(session)
        self.assertTrue(authority_is_active(lease))
        lease["lease_expires_at"] = time.time() - 1
        self.assertFalse(authority_is_active(lease))

    def test_preserve_newer_timer_authority(self) -> None:
        existing = {TIMER_AUTHORITY_KEY: {"user_id": "a", "lease_expires_at": 200}}
        outgoing = {TIMER_AUTHORITY_KEY: {"user_id": "b", "lease_expires_at": 100}}
        merged = preserve_shared_room_timer_authority(outgoing, existing)
        self.assertEqual(merged[TIMER_AUTHORITY_KEY]["user_id"], "a")

    def test_acquire_authority_on_shared_room(self) -> None:
        from draft_room_shared_state import shared_room_document

        doc = shared_room_document(
            room_code="AUTH01",
            host_participant_id="user:daniel",
            live_room={
                "draft_room_id": "R1",
                "status": "in_progress",
                "current_pick_index": 0,
                "teams": ["A", "B"],
                "draft_board": [],
            },
            revision=1,
        )
        self.store.save(doc)
        session = {
            "auth_user_id": "user:daniel",
            "draft_room_participant_id": "user:daniel",
            "active_shared_draft_room_code": "AUTH01",
        }
        with mock.patch("draft_room_context.is_multiplayer_draft_active", return_value=True):
            with mock.patch("draft_room_membership.is_room_host", return_value=True):
                with mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store):
                    ok, reason, saved = try_acquire_timer_authority(session, store=self.store)
        self.assertTrue(ok, reason)
        loaded = self.store.load("AUTH01")
        assert loaded is not None
        self.assertIn(TIMER_AUTHORITY_KEY, loaded)


class PreferencePersistenceTests(unittest.TestCase):
    def test_setup_survives_new_session_dict(self) -> None:
        session_a = {
            "auth_user_id": "user:daniel",
            "live_draft_team_count": 2,
            "live_draft_picks_per_team": 4,
            "live_draft_timer": "10 seconds",
            "live_draft_proj_window": "5 years",
            "live_draft_team_name_0": "Alpha",
            "live_draft_team_name_1": "Beta",
        }
        save_user_page_preferences(
            "user:daniel",
            "ws1",
            PAGE_KEY_LIVE_DRAFT_SETUP,
            collect_live_draft_setup_settings(session_a),
            session=session_a,
            force_disk=False,
        )
        # Simulate reboot: new session with page_filter_state restored from blob.
        session_b = {
            "auth_user_id": "user:daniel",
            "page_filter_state": session_a["page_filter_state"],
        }
        applied = ensure_live_draft_setup_preferences_loaded(session_b)
        self.assertTrue(applied)
        self.assertEqual(session_b.get("live_draft_team_count"), 2)
        self.assertEqual(session_b.get("live_draft_picks_per_team"), 4)
        self.assertEqual(session_b.get("live_draft_proj_window"), "5 years")
        self.assertEqual(session_b.get("live_draft_team_name_0"), "Alpha")
        self.assertTrue(preferences_initialized(session_b, PAGE_KEY_LIVE_DRAFT_SETUP))

    def test_initial_seed_does_not_mark_dirty_race(self) -> None:
        session = {
            "auth_user_id": "user:daniel",
            "page_filter_state": {
                "_user_page_preferences": {
                    PAGE_KEY_LIVE_DRAFT_SETUP: {
                        "user_id": "user:daniel",
                        "workspace_id": "",
                        "page_key": PAGE_KEY_LIVE_DRAFT_SETUP,
                        "schema_version": 1,
                        "settings": {"live_draft_proj_window": "5 years"},
                        "updated_at": "t",
                    }
                }
            },
        }
        ensure_live_draft_setup_preferences_loaded(session)
        self.assertEqual(session.get("live_draft_proj_window"), "5 years")
        self.assertFalse(session.get("_live_draft_setup_seeding"))

    def test_reset_setup_restores_defaults(self) -> None:
        session = {
            "auth_user_id": "user:daniel",
            "live_draft_proj_window": "5 years",
            "live_draft_team_count": 10,
        }
        reset_live_draft_setup_to_defaults(session, st=None)
        defaults = default_live_draft_setup_settings()
        self.assertEqual(session.get("live_draft_proj_window"), defaults["live_draft_proj_window"])
        self.assertEqual(session.get("live_draft_team_count"), defaults["live_draft_team_count"])
        prefs = get_user_page_preferences("user:daniel", "", PAGE_KEY_LIVE_DRAFT_SETUP, session=session)
        self.assertEqual(prefs.get("live_draft_proj_window"), defaults["live_draft_proj_window"])

    def test_users_have_separate_settings(self) -> None:
        session = {"page_filter_state": {}}
        save_user_page_preferences(
            "user:daniel",
            "ws",
            PAGE_KEY_LIVE_DRAFT_SETUP,
            {"live_draft_proj_window": "5 years"},
            session=session,
            force_disk=False,
        )
        # Different user id should not read Daniel's prefs when scoped.
        other = {
            "auth_user_id": "user:coakley11",
            "page_filter_state": session["page_filter_state"],
        }
        prefs = get_user_page_preferences("user:coakley11", "ws", PAGE_KEY_LIVE_DRAFT_SETUP, session=other)
        self.assertIsNone(prefs)

    def test_active_draft_skips_generic_pref_overwrite(self) -> None:
        session = {
            "auth_user_id": "user:daniel",
            "live_draft_room": {"status": "in_progress", "draft_room_id": "X"},
            "live_draft_proj_window": "3 years",
            "page_filter_state": {
                "_user_page_preferences": {
                    PAGE_KEY_LIVE_DRAFT_SETUP: {
                        "user_id": "user:daniel",
                        "settings": {"live_draft_proj_window": "5 years"},
                    }
                }
            },
        }
        applied = ensure_live_draft_setup_preferences_loaded(session)
        self.assertFalse(applied)
        self.assertEqual(session.get("live_draft_proj_window"), "3 years")

    def test_draft_mode_shared_survives_new_session(self) -> None:
        session_a = {"auth_user_id": "user:daniel", "workspace_id": "ws1"}
        set_live_draft_setup_mode(session_a, SETUP_MODE_SHARED, persist=True, st=None)
        self.assertEqual(get_live_draft_setup_mode(session_a), SETUP_MODE_SHARED)
        prefs = get_user_page_preferences("user:daniel", "ws1", PAGE_KEY_LIVE_DRAFT_SETUP, session=session_a)
        self.assertEqual(prefs.get("live_draft_setup_mode"), SETUP_MODE_SHARED)

        session_b = {
            "auth_user_id": "user:daniel",
            "workspace_id": "ws1",
            "page_filter_state": session_a["page_filter_state"],
        }
        applied = ensure_live_draft_setup_preferences_loaded(session_b)
        self.assertTrue(applied)
        self.assertEqual(get_live_draft_setup_mode(session_b), SETUP_MODE_SHARED)
        self.assertIn("Shared Multiplayer", str(session_b.get("_live_draft_mode_radio_label") or ""))

    def test_draft_mode_solo_survives_new_session(self) -> None:
        session_a = {"auth_user_id": "user:daniel", "workspace_id": "ws1"}
        set_live_draft_setup_mode(session_a, SETUP_MODE_SHARED, persist=True, st=None)
        set_live_draft_setup_mode(session_a, SETUP_MODE_SOLO, persist=True, st=None)
        session_b = {
            "auth_user_id": "user:daniel",
            "workspace_id": "ws1",
            "page_filter_state": session_a["page_filter_state"],
        }
        ensure_live_draft_setup_preferences_loaded(session_b)
        self.assertEqual(get_live_draft_setup_mode(session_b), SETUP_MODE_SOLO)

    def test_end_draft_restores_shared_mode_preference(self) -> None:
        from live_draft_completion import end_live_draft_session

        session = {
            "auth_user_id": "user:daniel",
            "workspace_id": "ws1",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            "live_draft_room": {
                "draft_room_id": "R1",
                "status": "completed",
                "config": {"draft_setup_mode": SETUP_MODE_SHARED, "league_name": "Test"},
            },
        }
        set_live_draft_setup_mode(session, SETUP_MODE_SHARED, persist=True, st=None)
        end_live_draft_session(session, st=None, reason="test_end")
        self.assertEqual(get_live_draft_setup_mode(session), SETUP_MODE_SHARED)
        self.assertIsNone(session.get("live_draft_room") or None)

    def test_completed_room_defers_to_session_preference(self) -> None:
        session = {
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            "live_draft_room": {
                "status": "completed",
                "config": {"draft_setup_mode": SETUP_MODE_SOLO},
            },
        }
        self.assertEqual(get_live_draft_setup_mode(session), SETUP_MODE_SHARED)

    def test_mode_recovered_after_init_when_session_key_missing(self) -> None:
        session = {
            "auth_user_id": "user:daniel",
            "workspace_id": "ws1",
            "_prefs_initialized:live_draft_setup": True,
            "page_filter_state": {
                "_user_page_preferences": {
                    PAGE_KEY_LIVE_DRAFT_SETUP: {
                        "user_id": "user:daniel",
                        "workspace_id": "ws1",
                        "settings": {"live_draft_setup_mode": SETUP_MODE_SHARED},
                    }
                }
            },
        }
        ensure_live_draft_setup_preferences_loaded(session)
        self.assertEqual(get_live_draft_setup_mode(session), SETUP_MODE_SHARED)

    def test_reset_setup_returns_mode_to_solo(self) -> None:
        session = {"auth_user_id": "user:daniel", "live_draft_setup_mode": SETUP_MODE_SHARED}
        set_live_draft_setup_mode(session, SETUP_MODE_SHARED, persist=True, st=None)
        reset_live_draft_setup_to_defaults(session, st=None)
        self.assertEqual(get_live_draft_setup_mode(session), SETUP_MODE_SOLO)
        prefs = get_user_page_preferences("user:daniel", "", PAGE_KEY_LIVE_DRAFT_SETUP, session=session)
        self.assertEqual(prefs.get("live_draft_setup_mode"), SETUP_MODE_SOLO)

    def test_restore_mode_preference_helper(self) -> None:
        session = {"auth_user_id": "user:daniel", "workspace_id": "ws1"}
        set_live_draft_setup_mode(session, SETUP_MODE_SHARED, persist=True, st=None)
        session.pop("live_draft_setup_mode", None)
        session.pop("_live_draft_mode_radio_label", None)
        mode = restore_live_draft_setup_mode_preference(session)
        self.assertEqual(mode, SETUP_MODE_SHARED)
        self.assertEqual(get_live_draft_setup_mode(session), SETUP_MODE_SHARED)

    def _mode_lifecycle(self, preferred: str) -> None:
        """Shared/Solo remain selected across create → finish → end → return → refresh → re-auth."""
        from draft_room_context import leave_shared_draft_room
        from live_draft_completion import end_live_draft_session

        session = {
            "auth_user_id": "user:daniel",
            "workspace_id": "ws-daniel",
            "_suite_active_workspace_id": "ws-daniel",
        }
        set_live_draft_setup_mode(session, preferred, persist=True, st=None)
        self.assertEqual(get_live_draft_setup_mode(session), preferred)

        # Create / run a draft room stamped with this mode.
        session["live_draft_room"] = {
            "draft_room_id": "LIFE1",
            "status": "in_progress",
            "config": {"draft_setup_mode": preferred, "league_name": "Lifecycle"},
        }
        self.assertEqual(get_live_draft_setup_mode(session), preferred)

        # Finish draft — completed room must not snap mode away from preference.
        session["live_draft_room"]["status"] = "completed"
        self.assertEqual(get_live_draft_setup_mode(session), preferred)

        # End session / leave room → still preferred on setup return.
        end_live_draft_session(session, st=None, reason="lifecycle_end")
        self.assertEqual(get_live_draft_setup_mode(session), preferred)

        # Navigate away and back (prefs already initialized; mode key missing).
        session.pop("live_draft_setup_mode", None)
        session.pop("_live_draft_mode_radio_label", None)
        ensure_live_draft_setup_preferences_loaded(session)
        self.assertEqual(get_live_draft_setup_mode(session), preferred)

        # Refresh / sign-out + sign-in: new session dict, same persisted page_filter_state.
        session_refresh = {
            "auth_user_id": "user:daniel",
            "workspace_id": "ws-daniel",
            "_suite_active_workspace_id": "ws-daniel",
            "page_filter_state": session["page_filter_state"],
        }
        ensure_live_draft_setup_preferences_loaded(session_refresh)
        self.assertEqual(get_live_draft_setup_mode(session_refresh), preferred)
        self.assertIn(
            "Shared Multiplayer" if preferred == SETUP_MODE_SHARED else "Solo Draft",
            str(session_refresh.get("_live_draft_mode_radio_label") or ""),
        )

        # Leave path also preserves preference.
        session_leave = {
            "auth_user_id": "user:daniel",
            "workspace_id": "ws-daniel",
            "_suite_active_workspace_id": "ws-daniel",
            "page_filter_state": session["page_filter_state"],
            "live_draft_setup_mode": preferred,
            "live_draft_room": {
                "draft_room_id": "LIFE2",
                "status": "not_started",
                "config": {"draft_setup_mode": preferred},
            },
            "active_shared_draft_room_code": "ABC123" if preferred == SETUP_MODE_SHARED else "",
            "draft_room_participant_id": "user:daniel",
        }
        with mock.patch(
            "draft_room_participant_state.save_participant_workflow_from_session"
        ), mock.patch("draft_room_participant_state.mark_participant_left_room"):
            leave_shared_draft_room(session_leave)
        self.assertEqual(get_live_draft_setup_mode(session_leave), preferred)

    def test_case1_shared_mode_lifecycle_persistence(self) -> None:
        self._mode_lifecycle(SETUP_MODE_SHARED)

    def test_case2_solo_mode_lifecycle_persistence(self) -> None:
        self._mode_lifecycle(SETUP_MODE_SOLO)

    def test_case3_old_room_does_not_overwrite_saved_preference(self) -> None:
        session = {
            "auth_user_id": "user:daniel",
            "workspace_id": "ws1",
            "_suite_active_workspace_id": "ws1",
        }
        set_live_draft_setup_mode(session, SETUP_MODE_SHARED, persist=True, st=None)
        # Old completed solo room still present — preference stays Shared.
        session["live_draft_room"] = {
            "draft_room_id": "OLD1",
            "status": "completed",
            "config": {"draft_setup_mode": SETUP_MODE_SOLO},
        }
        self.assertEqual(get_live_draft_setup_mode(session), SETUP_MODE_SHARED)
        # Starting/viewing an in-progress old room uses room stamp for that draft only.
        session["live_draft_room"]["status"] = "in_progress"
        self.assertEqual(get_live_draft_setup_mode(session), SETUP_MODE_SOLO)
        # After clearing the old room, saved preference returns to Shared.
        session.pop("live_draft_room", None)
        restore_live_draft_setup_mode_preference(session)
        self.assertEqual(get_live_draft_setup_mode(session), SETUP_MODE_SHARED)
        prefs = get_user_page_preferences("user:daniel", "ws1", PAGE_KEY_LIVE_DRAFT_SETUP, session=session)
        self.assertEqual(prefs.get("live_draft_setup_mode"), SETUP_MODE_SHARED)

    def test_case4_only_reset_setup_returns_mode_to_solo(self) -> None:
        from live_draft_completion import end_live_draft_session

        session = {
            "auth_user_id": "user:daniel",
            "workspace_id": "ws1",
            "_suite_active_workspace_id": "ws1",
        }
        set_live_draft_setup_mode(session, SETUP_MODE_SHARED, persist=True, st=None)
        session["live_draft_room"] = {
            "draft_room_id": "R",
            "status": "completed",
            "config": {"draft_setup_mode": SETUP_MODE_SHARED},
        }
        end_live_draft_session(session, st=None, reason="not_reset")
        self.assertEqual(get_live_draft_setup_mode(session), SETUP_MODE_SHARED)
        restore_live_draft_setup_mode_preference(session)
        self.assertEqual(get_live_draft_setup_mode(session), SETUP_MODE_SHARED)
        # Explicit Reset Setup is the intentional Solo return.
        reset_live_draft_setup_to_defaults(session, st=None)
        self.assertEqual(get_live_draft_setup_mode(session), SETUP_MODE_SOLO)

    def test_case5_daniel_and_coakley11_isolated_mode_prefs(self) -> None:
        daniel = {
            "auth_user_id": "user:daniel",
            "workspace_id": "ws-daniel",
            "_suite_active_workspace_id": "ws-daniel",
            "page_filter_state": {},
        }
        coakley = {
            "auth_user_id": "user:coakley11",
            "workspace_id": "ws-coakley",
            "_suite_active_workspace_id": "ws-coakley",
            "page_filter_state": {},
        }
        set_live_draft_setup_mode(daniel, SETUP_MODE_SHARED, persist=True, st=None)
        set_live_draft_setup_mode(coakley, SETUP_MODE_SOLO, persist=True, st=None)

        daniel_b = {
            "auth_user_id": "user:daniel",
            "workspace_id": "ws-daniel",
            "_suite_active_workspace_id": "ws-daniel",
            "page_filter_state": daniel["page_filter_state"],
        }
        coakley_b = {
            "auth_user_id": "user:coakley11",
            "workspace_id": "ws-coakley",
            "_suite_active_workspace_id": "ws-coakley",
            "page_filter_state": coakley["page_filter_state"],
        }
        ensure_live_draft_setup_preferences_loaded(daniel_b)
        ensure_live_draft_setup_preferences_loaded(coakley_b)
        self.assertEqual(get_live_draft_setup_mode(daniel_b), SETUP_MODE_SHARED)
        self.assertEqual(get_live_draft_setup_mode(coakley_b), SETUP_MODE_SOLO)
        # Cross-user: Coakley must not read Daniel's Shared preference from Daniel's blob.
        leaked = get_user_page_preferences(
            "user:coakley11", "ws-coakley", PAGE_KEY_LIVE_DRAFT_SETUP, session=daniel_b
        )
        self.assertIsNone(leaked)

    def test_case6_initial_render_does_not_overwrite_restored_shared(self) -> None:
        """ensure_…_loaded + apply must win before radio defaults; seeding skips persist races."""
        session = {
            "auth_user_id": "user:daniel",
            "workspace_id": "ws1",
            "_suite_active_workspace_id": "ws1",
            "page_filter_state": {
                "_user_page_preferences": {
                    PAGE_KEY_LIVE_DRAFT_SETUP: {
                        "user_id": "user:daniel",
                        "workspace_id": "ws1",
                        "page_key": PAGE_KEY_LIVE_DRAFT_SETUP,
                        "schema_version": 1,
                        "settings": {"live_draft_setup_mode": SETUP_MODE_SHARED},
                        "updated_at": "t",
                    }
                }
            },
        }
        # Simulate first paint: no mode key yet (widget default would be Solo).
        self.assertNotIn("live_draft_setup_mode", session)
        applied = ensure_live_draft_setup_preferences_loaded(session)
        self.assertTrue(applied)
        self.assertEqual(get_live_draft_setup_mode(session), SETUP_MODE_SHARED)
        self.assertIn("Shared Multiplayer", str(session.get("_live_draft_mode_radio_label") or ""))
        # Seeding flag cleared; a subsequent set during load must not have wiped prefs.
        self.assertFalse(session.get("_live_draft_setup_seeding"))
        prefs = get_user_page_preferences("user:daniel", "ws1", PAGE_KEY_LIVE_DRAFT_SETUP, session=session)
        self.assertEqual(prefs.get("live_draft_setup_mode"), SETUP_MODE_SHARED)


class ProjectionCacheTests(unittest.TestCase):
    def test_queue_tick_does_not_require_projection_recompute(self) -> None:
        from live_draft_projection_cache import should_recompute_projection, store_queue_projection
        from live_draft_rerun_scope import mark_live_draft_queue_tick

        session = {"draft_queue": ["A"], "live_draft_room": {"draft_room_id": "R", "current_pick_index": 0}}
        store_queue_projection(session, {"ok": True})
        mark_live_draft_queue_tick(session)
        self.assertFalse(should_recompute_projection(session))


class PollFragmentOwnsLoopTests(unittest.TestCase):
    def test_poll_apply_marks_optimistic_tick(self) -> None:
        from live_draft_safe_mode import request_poll_apply_rerun
        from live_draft_rerun_scope import live_draft_expensive_recompute_required

        session: dict = {}
        st = mock.MagicMock()
        with mock.patch("live_draft_safe_mode.is_rerun_allowed", return_value=(True, "")):
            with mock.patch("live_draft_safe_mode.record_rerun_diagnostics"):
                request_poll_apply_rerun(st, session)
        st.rerun.assert_called_once()
        self.assertTrue(session.get("_live_draft_recs_pending_after_pick"))
        self.assertFalse(live_draft_expensive_recompute_required(session))


class ExpirationAdvancesWithoutRecsTests(unittest.TestCase):
    def test_page_autopick_marks_optimistic_not_expensive_first(self) -> None:
        from live_draft_safe_mode import request_live_draft_rerun
        from live_draft_rerun_scope import live_draft_expensive_recompute_required

        session: dict = {}
        st = mock.MagicMock()
        with mock.patch("live_draft_safe_mode.is_rerun_allowed", return_value=(True, "")):
            with mock.patch("live_draft_safe_mode.record_rerun_diagnostics"):
                request_live_draft_rerun(st, session, "page_autopick")
        st.rerun.assert_called_once()
        self.assertTrue(session.get("_live_draft_recs_pending_after_pick"))
        self.assertFalse(live_draft_expensive_recompute_required(session))
        self.assertTrue(live_draft_expensive_recompute_required(session))


if __name__ == "__main__":
    unittest.main()

