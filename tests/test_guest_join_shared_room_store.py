"""Guest join must resolve get_shared_room_store without UnboundLocalError."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import create_and_host_shared_room, join_shared_draft_room
from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, LocalFileSharedRoomStore
from live_draft_setup_mode import SETUP_MODE_SHARED, finalize_shared_room_create, set_live_draft_setup_mode
from live_draft_setup_ui import _format_join_user_message, render_guest_join_from_setup
from shared_draft_permissions import is_canonical_commissioner


def _two_team_room() -> dict:
    pool = pd.DataFrame(
        [{"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"}]
    )
    return {
        "draft_room_id": "JOIN01",
        "status": "not_started",
        "current_pick_index": 0,
        "config": {
            "num_teams": 2,
            "your_team": "Team A",
            "user_team": "Team A",
            "teams": ["Team A", "Team B"],
            "draft_setup_mode": SETUP_MODE_SHARED,
        },
        "teams": ["Team A", "Team B"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team A"},
            {"Pick": 2, "Round": 1, "Team": "Team B"},
        ],
        "draft_board": [],
        "rosters": {"Team A": [], "Team B": []},
        "drafted_player_ids": [],
        "pool": pool,
    }


class GuestJoinSharedRoomStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        # Patch both the defining module and draft_room_context's imported binding.
        self._patches = [
            mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_context.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        self._tmpdir.cleanup()

    def test_join_without_injected_store_uses_module_get_shared_room_store(self) -> None:
        host = {
            "draft_room_participant_id": "daniel",
            "auth_user_id": "daniel",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
        }
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(
            host, _two_team_room(), host_team="Team A", store=self.store
        )
        self.assertFalse(err, err)
        self.assertTrue(code)

        guest = {
            "draft_room_participant_id": "coakley11",
            "auth_user_id": "coakley11",
        }
        # No store= — must call module-level get_shared_room_store() without UnboundLocalError.
        ok, msg, doc = join_shared_draft_room(guest, code, requested_team="Team B")
        self.assertTrue(ok, msg)
        self.assertIsInstance(doc, dict)
        parts = dict((doc or {}).get("participants") or {})
        self.assertEqual(
            str((parts.get("coakley11") or {}).get("assigned_team") or ""),
            "Team B",
        )

    def test_join_with_injected_fake_store(self) -> None:
        host = {
            "draft_room_participant_id": "daniel",
            "auth_user_id": "daniel",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
        }
        code, err = finalize_shared_room_create(
            host, _two_team_room(), host_team="Team A", store=self.store
        )
        self.assertFalse(err, err)

        guest = {"draft_room_participant_id": "coakley11", "auth_user_id": "coakley11"}
        ok, msg, doc = join_shared_draft_room(
            guest, code, requested_team="Team B", store=self.store
        )
        self.assertTrue(ok, msg)
        self.assertIsInstance(doc, dict)

    def test_daniel_create_coakley11_guest_team_b_not_commissioner(self) -> None:
        host = {
            "draft_room_participant_id": "daniel",
            "auth_user_id": "daniel",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            "preferred_next_draft_mode": SETUP_MODE_SHARED,
        }
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _two_team_room()
        code, document = create_and_host_shared_room(
            host, room, host_team="Team A", store=self.store
        )
        self.assertTrue(code, "missing room code")
        self.assertIsInstance(document, dict)
        self.assertEqual(host.get(ACTIVE_SHARED_ROOM_CODE_KEY), code)
        self.assertTrue(is_canonical_commissioner(host, document))

        guest = {
            "draft_room_participant_id": "coakley11",
            "auth_user_id": "coakley11",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
        }
        ok, msg, doc = join_shared_draft_room(
            guest, code, requested_team="Team B", store=self.store
        )
        self.assertTrue(ok, msg)
        self.assertEqual(str(guest.get("draft_room_participant_team") or ""), "Team B")
        self.assertEqual(guest.get(ACTIVE_SHARED_ROOM_CODE_KEY), code)
        self.assertFalse(
            is_canonical_commissioner(guest, doc),
            "Coakley11 must remain a guest, not commissioner",
        )
        self.assertEqual(
            str((doc or {}).get("commissioner_participant_id") or ""),
            "daniel",
        )

    def test_invalid_code_returns_validation_message_not_crash(self) -> None:
        guest = {"draft_room_participant_id": "coakley11"}
        ok, msg, doc = join_shared_draft_room(guest, "ZZZZZZ", requested_team="Team B")
        self.assertFalse(ok)
        self.assertIsNone(doc)
        self.assertIn("not found", msg.lower())

    def test_backend_unavailable_restores_join_form_safe_error(self) -> None:
        class BrokenStore:
            def load(self, _code: str):
                raise RuntimeError("backend unavailable")

            def save(self, document):
                raise RuntimeError("backend unavailable")

        guest = {
            "draft_room_participant_id": "coakley11",
            "_join_shared_draft_from_setup": True,
            "_join_requested_code": "ABCDEF",
            "_join_requested_team": "Team B",
        }

        class _St:
            def __init__(self) -> None:
                self.errors: list[str] = []
                self.successes: list[str] = []

            def error(self, msg: str) -> None:
                self.errors.append(str(msg))

            def success(self, msg: str) -> None:
                self.successes.append(str(msg))

        ok, msg, doc = join_shared_draft_room(
            {"draft_room_participant_id": "coakley11"},
            "ABCDEF",
            requested_team="Team B",
            store=BrokenStore(),  # type: ignore[arg-type]
        )
        self.assertFalse(ok)
        self.assertIsNone(doc)
        self.assertTrue(msg)
        self.assertIn("backend unavailable", msg.lower())

        with mock.patch(
            "draft_room_context.join_shared_draft_room",
            return_value=(
                False,
                "Could not look up room **ABCDEF** (local): backend unavailable",
                None,
            ),
        ):
            st = _St()
            need_rerun = render_guest_join_from_setup(st, guest)
            self.assertFalse(need_rerun)
            self.assertTrue(guest.get("_draft_join_error"))
            self.assertIsNone(guest.get("_draft_join_flash"))
            display = _format_join_user_message(
                ok=False,
                code="ABCDEF",
                team="Team B",
                backend_msg=str(guest.get("_draft_join_error")),
            )
            self.assertIn("could not join", display.lower())


if __name__ == "__main__":
    unittest.main()
