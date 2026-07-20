"""P0 Supabase egress hardening — chat status, poll interval, autosave, minimal writes."""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from draft_room_shared_state import (
    SHARED_DOC_SOFT_CACHE_KEY,
    shared_room_document,
)
from live_draft_chat import CHAT_STATUS_DOC_KEY, refresh_live_draft_chat_if_newer
from live_draft_chat_ui import (
    CHAT_POLL_INTERVAL_KEY,
    format_chat_participant_status_line,
)
from suite_egress_policy import (
    SHARED_DRAFT_POLL_INTERVAL_SEC,
    SHARED_DRAFT_POLL_LOW_EGRESS_SEC,
    cloud_autosave_allowed,
    set_low_egress_mode,
    shared_draft_poll_interval_sec,
)


class TestChatStatusNoFullRoom(unittest.TestCase):
    def test_format_status_does_not_call_load_shared_room(self) -> None:
        session = {
            "active_shared_draft_room_code": "ABCD12",
            "live_draft_room": {
                "teams": ["Team A", "Team B"],
                "config": {"num_teams": 2},
            },
            CHAT_STATUS_DOC_KEY: {
                "host_user_id": "user:daniel",
                "host_participant_id": "user:daniel",
                "joined_participants": {
                    "user:daniel": {
                        "user_id": "user:daniel",
                        "display_name": "Daniel",
                        "team_name": "Team A",
                    }
                },
                "participants": {
                    "user:daniel": {
                        "assigned_team": "Team A",
                        "display_name": "Daniel",
                    }
                },
            },
        }
        with patch(
            "draft_room_shared_state.load_shared_room",
            side_effect=AssertionError("full room must not load"),
        ):
            line = format_chat_participant_status_line(session)
        self.assertIn("Daniel", line)
        self.assertIn("Team A", line)

    def test_required_rows_allow_network_false_skips_load(self) -> None:
        from live_draft_presence import required_human_participant_rows

        session = {"active_shared_draft_room_code": "ABCD12"}
        room = {"teams": ["Team A"], "config": {"num_teams": 1}}
        with patch(
            "draft_room_shared_state.load_shared_room",
            side_effect=AssertionError("must not load"),
        ):
            rows = required_human_participant_rows(
                session, room, document=None, allow_network=False
            )
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].get("waiting"))


class TestChatRefreshSidecarOnly(unittest.TestCase):
    def test_one_refresh_no_full_room_and_at_most_one_sidecar(self) -> None:
        class _Store:
            def __init__(self) -> None:
                self.full_loads = 0
                self.chat_loads = 0

            def load(self, _code: str):
                self.full_loads += 1
                raise AssertionError("full room load must not run for chat refresh")

            def load_chat_sidecar(self, code: str):
                self.chat_loads += 1
                return {
                    "room_code": code,
                    "revision": 3,
                    "host_user_id": "user:daniel",
                    "host_participant_id": "user:daniel",
                    "joined_participants": {
                        "user:daniel": {
                            "user_id": "user:daniel",
                            "display_name": "Daniel",
                            "team_name": "Team A",
                        }
                    },
                    "participants": {
                        "user:daniel": {"assigned_team": "Team A", "display_name": "Daniel"}
                    },
                    "chat": {
                        "chat_revision": 2,
                        "messages": [
                            {
                                "id": "m1",
                                "participant_id": "p1",
                                "text": "hi",
                                "ts": "2026-01-01T00:00:00Z",
                                "visibility": "public",
                            }
                        ],
                    },
                }

        store = _Store()
        session = {
            "active_shared_draft_room_code": "ABCD12",
            "draft_room_participant_id": "p1",
            "live_draft_room": {"teams": ["Team A", "Team B"], "config": {"num_teams": 2}},
        }
        with patch("draft_room_shared_state.get_shared_room_store", return_value=store):
            refresh_live_draft_chat_if_newer(session)
            line = format_chat_participant_status_line(session)
        self.assertEqual(store.full_loads, 0)
        self.assertEqual(store.chat_loads, 1)
        self.assertIn("Daniel", line)
        self.assertIsInstance(session.get(CHAT_STATUS_DOC_KEY), dict)


class TestChatPollInterval(unittest.TestCase):
    def test_low_egress_chat_interval_near_eight(self) -> None:
        session: dict = {}
        set_low_egress_mode(session, True)
        self.assertEqual(shared_draft_poll_interval_sec(session), SHARED_DRAFT_POLL_LOW_EGRESS_SEC)
        self.assertGreaterEqual(SHARED_DRAFT_POLL_LOW_EGRESS_SEC, 7.5)

    def test_normal_chat_interval_uses_configured(self) -> None:
        session: dict = {}
        self.assertEqual(shared_draft_poll_interval_sec(session), SHARED_DRAFT_POLL_INTERVAL_SEC)

    def test_chat_ui_uses_shared_draft_poll_interval(self) -> None:
        src = Path(__file__).resolve().parents[1].joinpath("live_draft_chat_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("shared_draft_poll_interval_sec(session)", src)
        self.assertIn(CHAT_POLL_INTERVAL_KEY, src)
        self.assertNotIn("timedelta(seconds=float(CHAT_POLL_SEC))", src)


class TestAutosaveHardening(unittest.TestCase):
    def test_autosave_throttled(self) -> None:
        st = MagicMock()
        st.session_state = {"_suite_last_cloud_autosave_ts": time.time()}
        allowed, reason = cloud_autosave_allowed(st, "baseball", save_reason="autosave")
        self.assertFalse(allowed)
        self.assertEqual(reason, "autosave_throttled")

    def test_routine_autosave_skips_merge_get_when_cache_warm(self) -> None:
        from suite_storage_supabase import (
            _METRICS_MERGE_CACHE,
            _merge_state_metrics,
            remember_metrics_merge_cache,
        )

        _METRICS_MERGE_CACHE.clear()
        remember_metrics_merge_cache("baseball", {"full_session": {"a": 1}, "other": 2})
        with patch("suite_storage_supabase._request") as mock_req:
            merged = _merge_state_metrics(
                "baseball",
                {"full_session": {"a": 2}},
                allow_network=False,
            )
        mock_req.assert_not_called()
        self.assertEqual(merged.get("other"), 2)
        self.assertEqual((merged.get("full_session") or {}).get("a"), 2)

    def test_autosave_path_no_readback_in_source(self) -> None:
        src = Path(__file__).resolve().parents[1].joinpath("suite_user_persistence.py").read_text(
            encoding="utf-8"
        )
        # Routine autosave must not immediately reload full_session after write.
        self.assertIn("skip_metrics_merge_read=True", src)
        self.assertNotIn(
            "_, cloud_ts_after = load_cloud_full_session(app_id)",
            src,
        )


class TestMinimalWriteResponses(unittest.TestCase):
    def test_save_if_revision_uses_return_minimal(self) -> None:
        from draft_room_supabase_store import SupabaseSharedRoomStore, document_to_row

        store = SupabaseSharedRoomStore()
        doc = shared_room_document(
            room_code="ABC123",
            host_participant_id="host",
            live_room={
                "draft_room_id": "R1",
                "status": "lobby",
                "config": {"num_teams": 2},
                "teams": ["Team 1", "Team 2"],
                "rosters": {"Team 1": [], "Team 2": []},
                "draft_board": [],
                "pool_records": [],
                "pool_columns": [],
            },
            revision=1,
        )
        doc["chat"] = {"messages": [], "chat_revision": 1}
        with patch("draft_room_supabase_store._request") as mock_request:
            mock_request.side_effect = [
                [{"room_code": "ABC123", "revision": 1, "status": "", "updated_at": ""}],
                [],
            ]
            ok, saved = store.save_if_revision(doc, expected_revision=1)
        self.assertTrue(ok)
        self.assertIsNotNone(saved)
        self.assertEqual(mock_request.call_count, 2)
        patch_kwargs = mock_request.call_args_list[1].kwargs
        self.assertEqual(patch_kwargs.get("prefer"), "return=minimal")
        # No third full-room GET after successful minimal write.
        methods = [c.args[0] for c in mock_request.call_args_list]
        self.assertEqual(methods.count("GET"), 1)
        self.assertEqual(methods.count("PATCH"), 1)
        _ = document_to_row  # import kept for parity with older tests


class TestSoftCachePeek(unittest.TestCase):
    def test_status_uses_soft_cache_without_network(self) -> None:
        doc = shared_room_document(
            room_code="ABCD12",
            host_participant_id="user:daniel",
            live_room={
                "draft_room_id": "R1",
                "status": "lobby",
                "config": {"num_teams": 2},
                "teams": ["Team A", "Team B"],
                "rosters": {"Team A": [], "Team B": []},
                "draft_board": [],
                "pool_records": [],
                "pool_columns": [],
            },
            revision=1,
        )
        doc["host_user_id"] = "user:daniel"
        doc["participants"] = {
            "user:daniel": {"assigned_team": "Team A", "display_name": "Daniel"},
            "user:coak": {"assigned_team": "Team B", "display_name": "Coakley11"},
        }
        doc["joined_participants"] = {
            "user:daniel": {
                "user_id": "user:daniel",
                "display_name": "Daniel",
                "team_name": "Team A",
            },
            "user:coak": {
                "user_id": "user:coak",
                "display_name": "Coakley11",
                "team_name": "Team B",
            },
        }
        session = {
            "active_shared_draft_room_code": "ABCD12",
            "live_draft_room": doc.get("room"),
            SHARED_DOC_SOFT_CACHE_KEY: {
                "room_code": "ABCD12",
                "loaded_at": time.time(),
                "document": doc,
            },
        }
        with patch(
            "draft_room_shared_state.load_shared_room",
            side_effect=AssertionError("no network"),
        ):
            line = format_chat_participant_status_line(session)
        self.assertIn("Daniel", line)
        self.assertIn("Coakley11", line)


if __name__ == "__main__":
    unittest.main()
