"""Production-path Continue / Replace button ops (force_setup must not wipe)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import create_and_host_shared_room
from draft_room_shared_state import LocalFileSharedRoomStore, bump_revision
from live_draft_completion import LIFECYCLE_SETUP, LIFECYCLE_WAITING_SHARED_LOBBY, resolve_live_draft_lifecycle
from live_draft_resumable_ops import (
    OP_PENDING_KEY,
    OP_RECEIPT_KEY,
    begin_op,
    execute_continue_saved,
    execute_replace_transactional,
    get_op_receipt,
    on_continue_saved_click,
    process_pending_resumable_ops,
)
from live_draft_resumable_slot import RESUMABLE_LIVE_DRAFT_SLOT_KEY, get_resumable_live_draft_slot
from live_draft_resume_lobby import stamp_resume_reserved_on_document
from live_draft_setup_mode import SETUP_MODE_SHARED, set_live_draft_setup_mode


def _room(**overrides) -> dict:
    room = {
        "draft_room_id": "OPS001",
        "status": "in_progress",
        "current_pick_index": 2,
        "config": {
            "num_teams": 2,
            "picks_per_team": 4,
            "timer_seconds": 60,
            "your_team": "Team A",
            "user_team": "Team A",
            "teams": ["Team A", "Team B"],
            "draft_setup_mode": SETUP_MODE_SHARED,
        },
        "teams": ["Team A", "Team B"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team A"},
            {"Pick": 2, "Round": 1, "Team": "Team B"},
            {"Pick": 3, "Round": 2, "Team": "Team B"},
            {"Pick": 4, "Round": 2, "Team": "Team A"},
        ],
        "draft_board": [
            {"Pick": 1, "Team": "Team A", "Player": "A", "playerID": "p1"},
            {"Pick": 2, "Team": "Team B", "Player": "B", "playerID": "p2"},
        ],
        "rosters": {"Team A": [], "Team B": []},
        "drafted_player_ids": ["p1", "p2"],
        "pool": pd.DataFrame(
            [{"playerID": f"p{i}", "fullName": f"P{i}", "Primary Position": "OF"} for i in range(20)]
        ),
    }
    room.update(overrides)
    return room


class ResumableOpsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self._patches = [
            mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_context.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False),
            mock.patch("baseball_persistent_state.force_save_baseball_state", return_value=True),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        self._tmpdir.cleanup()

    def _park(self, session: dict, code: str, room: dict) -> None:
        doc = stamp_resume_reserved_on_document(self.store.load(code))
        self.store.save(bump_revision(doc))
        session[RESUMABLE_LIVE_DRAFT_SLOT_KEY] = {
            "kind": "resumable_live_draft_slot",
            "draft_id": room["draft_room_id"],
            "room_id": room["draft_room_id"],
            "room_code": code,
            "is_shared": True,
            "participant_id": "daniel",
            "participant_team": "Team A",
            "room": dict(room),
            "queues": {"draft_queue": ["Keep"]},
            "summary": {"current_pick": 3, "total_picks": 4, "num_teams": 2, "mode_label": "Shared"},
        }
        session.pop("live_draft_room", None)
        session.pop("active_shared_draft_room_code", None)

    def test_force_setup_does_not_wipe_continue_resume_lobby(self) -> None:
        host = {
            "draft_room_participant_id": "daniel",
            "auth_user_id": "daniel",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            # The deployed no-op: prior End/Delete left this sticky.
            "_live_draft_force_setup_after_delete": True,
            "_live_draft_deleting": "done",
        }
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _room()
        code, _ = create_and_host_shared_room(host, room, host_team="Team A", store=self.store)
        self._park(host, code, room)

        begin_op(
            host,
            action="continue_saved",
            button_label="Continue Saved Draft",
            widget_key="live_draft_continue_saved_btn",
        )
        result = execute_continue_saved(host)
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(host.get("_live_draft_resume_lobby"))
        self.assertIsInstance(host.get("live_draft_room"), dict)
        self.assertFalse(host.get("_live_draft_force_setup_after_delete"))

        life = resolve_live_draft_lifecycle(host, room=host.get("live_draft_room"))
        self.assertEqual(life, LIFECYCLE_WAITING_SHARED_LOBBY)
        self.assertEqual(int(host["live_draft_room"].get("current_pick_index") or 0), 2)
        receipt = get_op_receipt(host)
        self.assertTrue(receipt.get("click_detected"))
        self.assertEqual(receipt.get("widget_key"), "live_draft_continue_saved_btn")
        self.assertIn(receipt.get("last_completed_step"), ("finished", "lifecycle_after_continue", "full_app_rerun_requested"))

    def test_replace_keeps_slot_on_create_failure(self) -> None:
        host = {
            "draft_room_participant_id": "daniel",
            "auth_user_id": "daniel",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            "preferred_next_draft_mode": SETUP_MODE_SHARED,
        }
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _room()
        code, _ = create_and_host_shared_room(host, room, host_team="Team A", store=self.store)
        self._park(host, code, room)
        slot_before = dict(get_resumable_live_draft_slot(host) or {})

        with mock.patch(
            "live_draft_setup_mode.finalize_shared_room_create",
            return_value=("", "simulated create failure"),
        ):
            rep = execute_replace_transactional(host)
        self.assertFalse(rep.get("ok"))
        self.assertTrue(rep.get("slot_kept"))
        self.assertIsNotNone(get_resumable_live_draft_slot(host))
        self.assertEqual(
            str((get_resumable_live_draft_slot(host) or {}).get("room_code") or "").upper(),
            code,
        )
        # Old room must not be deleted when create fails.
        doc = self.store.load(code)
        self.assertNotEqual(str((doc or {}).get("status") or "").lower(), "deleted")
        self.assertEqual(slot_before.get("draft_id"), (get_resumable_live_draft_slot(host) or {}).get("draft_id"))

    def test_replace_tombstones_only_after_new_room_success(self) -> None:
        host = {
            "draft_room_participant_id": "daniel",
            "auth_user_id": "daniel",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            "preferred_next_draft_mode": SETUP_MODE_SHARED,
        }
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _room()
        code, _ = create_and_host_shared_room(host, room, host_team="Team A", store=self.store)
        self._park(host, code, room)

        rep = execute_replace_transactional(host)
        self.assertTrue(rep.get("ok"), rep)
        new_code = str(rep.get("new_room_code") or "")
        self.assertTrue(new_code)
        self.assertNotEqual(new_code, code)
        self.assertIsNone(get_resumable_live_draft_slot(host))
        self.assertEqual(str((self.store.load(code) or {}).get("status") or "").lower(), "deleted")
        new_doc = self.store.load(new_code)
        self.assertIsInstance(new_doc, dict)
        self.assertEqual(host.get("active_shared_draft_room_code"), new_code)
        live = host.get("live_draft_room") or {}
        self.assertIsInstance(live, dict)
        self.assertEqual(int(live.get("current_pick_index", -1)), 0)

    def test_on_click_pending_processed_like_streamlit_app(self) -> None:
        """Simulate streamlit on_click → process_pending at page top."""
        host = {
            "draft_room_participant_id": "daniel",
            "auth_user_id": "daniel",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            "_live_draft_force_setup_after_delete": True,
        }
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _room()
        code, _ = create_and_host_shared_room(host, room, host_team="Team A", store=self.store)
        self._park(host, code, room)

        begin_op(
            host,
            action="continue_saved",
            button_label="Continue Saved Draft",
            widget_key="live_draft_continue_saved_btn",
        )
        host[OP_PENDING_KEY] = "continue_saved"

        class _St:
            def __init__(self) -> None:
                self.session_state = host
                self.rerun_called = False
                self.stop_called = False

            def rerun(self) -> None:
                self.rerun_called = True
                raise RuntimeError("rerun")

            def stop(self) -> None:
                self.stop_called = True

        st = _St()
        with self.assertRaises(RuntimeError):
            process_pending_resumable_ops(host, st=st)
        self.assertTrue(st.rerun_called)
        self.assertTrue(host.get("_live_draft_resume_lobby"))
        self.assertEqual(
            resolve_live_draft_lifecycle(host, room=host.get("live_draft_room")),
            LIFECYCLE_WAITING_SHARED_LOBBY,
        )
        # Without resume flag, force_setup would have forced SETUP.
        host2 = {"_live_draft_force_setup_after_delete": True, "_live_draft_deleting": "done"}
        self.assertEqual(resolve_live_draft_lifecycle(host2), LIFECYCLE_SETUP)


if __name__ == "__main__":
    unittest.main()
