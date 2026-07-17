"""Shared Live Draft presence + Start Draft gating regressions."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import create_and_host_shared_room, join_shared_draft_room
from draft_room_shared_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    LocalFileSharedRoomStore,
    preserve_shared_room_participants,
    reset_shared_room_store_for_tests,
)
from live_draft_presence import (
    JOINED_PARTICIPANTS_KEY,
    count_required_joined,
    format_participant_status_line,
    mark_participant_present,
)
from live_draft_setup_mode import SETUP_MODE_SHARED, can_start_live_draft, set_live_draft_setup_mode
from suite_auth import AUTH_USER_ID_KEY


def _room(*, teams=None, status: str = "not_started") -> dict:
    teams = teams or ["Team 1", "Team 2"]
    return {
        "draft_room_id": "PRES1",
        "status": status,
        "current_pick_index": 0,
        "config": {
            "num_teams": len(teams),
            "your_team": teams[0],
            "user_team": teams[0],
            "teams": teams,
            "draft_setup_mode": SETUP_MODE_SHARED,
        },
        "teams": teams,
        "pick_order": [{"Pick": i + 1, "Round": 1, "Team": teams[i % len(teams)]} for i in range(4)],
        "draft_board": [],
        "rosters": {t: [] for t in teams},
        "drafted_player_ids": [],
        "pool": pd.DataFrame([{"playerID": "p1", "fullName": "A", "Primary Position": "OF"}]),
    }


class PresenceJoinTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmp.name))
        reset_shared_room_store_for_tests(self.store)
        self.daniel = {
            AUTH_USER_ID_KEY: "user:daniel",
            "draft_room_participant_id": "user:daniel",
            "room_your_team": "Team 1",
            "participant_display_name": "Daniel",
        }
        self.coakley = {
            AUTH_USER_ID_KEY: "user:coakley11",
            "draft_room_participant_id": "user:coakley11",
            "participant_display_name": "Coakley11",
        }
        self._patches = [
            mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        reset_shared_room_store_for_tests(None)
        self._tmp.cleanup()

    def test_second_account_enters_and_becomes_joined(self) -> None:
        set_live_draft_setup_mode(self.daniel, SETUP_MODE_SHARED)
        room = _room()
        code, _ = create_and_host_shared_room(self.daniel, room, store=self.store)
        self.assertTrue(code)
        ok, msg, _ = join_shared_draft_room(self.coakley, code, requested_team="Team 2", store=self.store)
        self.assertTrue(ok, msg)
        mark_participant_present(self.coakley, force_save=True, store=self.store)

        doc = self.store.load(code)
        assert doc is not None
        joined = doc.get(JOINED_PARTICIPANTS_KEY) or {}
        self.assertIn("user:daniel", joined)
        self.assertIn("user:coakley11", joined)

        joined_n, total, rows = count_required_joined(self.daniel, room, document=doc)
        self.assertEqual(total, 2)
        self.assertEqual(joined_n, 2)
        labels = [format_participant_status_line(r) for r in rows]
        self.assertTrue(any("Joined" in x and "Team 2" in x for x in labels))

    def test_commissioner_sees_second_account_immediately(self) -> None:
        set_live_draft_setup_mode(self.daniel, SETUP_MODE_SHARED)
        room = _room()
        self.daniel["live_draft_room"] = room
        code, _ = create_and_host_shared_room(self.daniel, room, store=self.store)
        self.assertTrue(code)
        self.daniel[ACTIVE_SHARED_ROOM_CODE_KEY] = code
        if not isinstance(self.daniel.get("live_draft_room"), dict):
            self.daniel["live_draft_room"] = room
        join_shared_draft_room(self.coakley, code, requested_team="Team 2", store=self.store)
        # Daniel reloads gate without recreating the league.
        ok, reason = can_start_live_draft(self.daniel)
        self.assertTrue(ok, reason)

    def test_refresh_does_not_remove_joined_state(self) -> None:
        set_live_draft_setup_mode(self.daniel, SETUP_MODE_SHARED)
        room = _room()
        code, _ = create_and_host_shared_room(self.daniel, room, store=self.store)
        join_shared_draft_room(self.coakley, code, requested_team="Team 2", store=self.store)
        before = dict((self.store.load(code) or {}).get(JOINED_PARTICIPANTS_KEY) or {})
        mark_participant_present(self.daniel, force_save=True, store=self.store)
        after = dict((self.store.load(code) or {}).get(JOINED_PARTICIPANTS_KEY) or {})
        self.assertIn("user:coakley11", after)
        self.assertEqual(set(before.keys()) | {"user:daniel"}, set(after.keys()) | set(before.keys()))

    def test_stale_host_save_preserves_guest_participant(self) -> None:
        existing = {
            "participants": {
                "user:daniel": {"assigned_team": "Team 1", "display_name": "Daniel", "joined_at": "t0"},
                "user:coakley11": {"assigned_team": "Team 2", "display_name": "Coakley11", "joined_at": "t1"},
            },
            JOINED_PARTICIPANTS_KEY: {
                "user:daniel": {"user_id": "user:daniel", "team_name": "Team 1", "joined_at": "t0", "last_seen_at": "t0"},
                "user:coakley11": {
                    "user_id": "user:coakley11",
                    "team_name": "Team 2",
                    "joined_at": "t1",
                    "last_seen_at": "t1",
                },
            },
        }
        stale_host = {
            "participants": {
                "user:daniel": {"assigned_team": "Team 1", "display_name": "Daniel", "joined_at": "t0"},
            },
            JOINED_PARTICIPANTS_KEY: {
                "user:daniel": {"user_id": "user:daniel", "team_name": "Team 1", "joined_at": "t0", "last_seen_at": "t2"},
            },
        }
        merged = preserve_shared_room_participants(stale_host, existing)
        self.assertIn("user:coakley11", merged["participants"])
        self.assertIn("user:coakley11", merged[JOINED_PARTICIPANTS_KEY])

    def test_cpu_placeholder_does_not_block_start(self) -> None:
        set_live_draft_setup_mode(self.daniel, SETUP_MODE_SHARED)
        room = _room(teams=["Team 1", "Team 2", "CPU Bot"])
        code, _ = create_and_host_shared_room(self.daniel, room, store=self.store)
        join_shared_draft_room(self.coakley, code, requested_team="Team 2", store=self.store)
        doc = self.store.load(code)
        assert doc is not None
        parts = dict(doc.get("participants") or {})
        parts["cpu:bot"] = {
            "assigned_team": "CPU Bot",
            "display_name": "CPU",
            "joined_at": "t",
            "is_cpu": True,
            "seat_kind": "cpu",
        }
        doc["participants"] = parts
        self.store.save(doc)
        self.daniel["live_draft_room"] = room
        self.daniel[ACTIVE_SHARED_ROOM_CODE_KEY] = code
        joined_n, total, rows = count_required_joined(self.daniel, room, document=self.store.load(code))
        self.assertEqual(total, 2)
        self.assertEqual(joined_n, 2)
        self.assertFalse(any(r.get("team_name") == "CPU Bot" for r in rows))

    def test_absent_required_participant_blocks_start(self) -> None:
        set_live_draft_setup_mode(self.daniel, SETUP_MODE_SHARED)
        room = _room()
        self.daniel["live_draft_room"] = room
        code, _ = create_and_host_shared_room(self.daniel, room, store=self.store)
        self.assertTrue(code)
        self.daniel[ACTIVE_SHARED_ROOM_CODE_KEY] = code
        if not isinstance(self.daniel.get("live_draft_room"), dict):
            self.daniel["live_draft_room"] = room
        # Only host present — Coakley has not claimed/joined.
        ok, reason = can_start_live_draft(self.daniel)
        self.assertFalse(ok)
        self.assertTrue(
            any(tok in reason.lower() for tok in ("participant", "manager", "claim", "join")),
            reason,
        )

    def test_email_alias_does_not_duplicate_participant(self) -> None:
        set_live_draft_setup_mode(self.daniel, SETUP_MODE_SHARED)
        room = _room()
        code, _ = create_and_host_shared_room(self.daniel, room, store=self.store)
        # Same auth id, different display name / email aliases in session.
        alias = {
            AUTH_USER_ID_KEY: "user:coakley11",
            "draft_room_participant_id": "user:coakley11",
            "participant_display_name": "coakley11@example.com",
            "_suite_auth_user_email": "coakley.alias@example.com",
        }
        ok, msg, _ = join_shared_draft_room(alias, code, requested_team="Team 2", store=self.store)
        self.assertTrue(ok, msg)
        mark_participant_present(alias, force_save=True, store=self.store)
        # Re-enter with a different display name — still one participant id.
        alias2 = dict(alias)
        alias2["participant_display_name"] = "Coakley Workspace"
        mark_participant_present(alias2, force_save=True, store=self.store)
        doc = self.store.load(code)
        assert doc is not None
        joined = doc.get(JOINED_PARTICIPANTS_KEY) or {}
        self.assertEqual(1, sum(1 for k in joined if "coakley" in k.lower() or k == "user:coakley11"))


class ChatSharedScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmp.name))
        reset_shared_room_store_for_tests(self.store)
        self.daniel = {
            AUTH_USER_ID_KEY: "user:daniel",
            "draft_room_participant_id": "user:daniel",
            "room_your_team": "Team 1",
            "participant_display_name": "Daniel",
        }
        self.coakley = {
            AUTH_USER_ID_KEY: "user:coakley11",
            "draft_room_participant_id": "user:coakley11",
            "participant_display_name": "Coakley11",
        }
        self._patches = [
            mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False),
            mock.patch("draft_room_context.is_multiplayer_draft_active", return_value=True),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        reset_shared_room_store_for_tests(None)
        self._tmp.cleanup()

    def test_two_accounts_share_one_chat_history(self) -> None:
        from live_draft_chat import (
            append_live_draft_chat_message,
            canonical_chat_scope,
            load_live_draft_chat,
            user_visible_messages,
        )

        set_live_draft_setup_mode(self.daniel, SETUP_MODE_SHARED)
        room = _room(status="in_progress")
        code, _ = create_and_host_shared_room(self.daniel, room, store=self.store)
        join_shared_draft_room(self.coakley, code, requested_team="Team 2", store=self.store)
        self.daniel["live_draft_room"] = room
        self.coakley["live_draft_room"] = dict(room)
        self.coakley["room_your_team"] = "Team 2"

        scope_d = canonical_chat_scope(self.daniel)
        scope_c = canonical_chat_scope(self.coakley)
        self.assertEqual(scope_d, scope_c)
        self.assertTrue(scope_d.startswith("league:"))

        with mock.patch(
            "draft_room_participant_state.resolve_participant_id",
            side_effect=lambda s: s.get(AUTH_USER_ID_KEY),
        ):
            with mock.patch(
                "draft_room_participant_state.active_participant_team",
                side_effect=lambda s: s.get("room_your_team") or "Team 1",
            ):
                ok, err = append_live_draft_chat_message(self.daniel, "Testing from Daniel")
                self.assertTrue(ok, err)
                chat_c = load_live_draft_chat(self.coakley, force=True)
                self.assertEqual(chat_c["messages"][-1]["text"], "Testing from Daniel")

                ok, err = append_live_draft_chat_message(self.coakley, "Testing from Coakley11")
                self.assertTrue(ok, err)
                chat_d = load_live_draft_chat(self.daniel, force=True)
                texts = [m["text"] for m in chat_d["messages"]]
                self.assertEqual(texts[-2:], ["Testing from Daniel", "Testing from Coakley11"])

                for i in range(6):
                    append_live_draft_chat_message(self.daniel, f"Msg {i}")
                visible = user_visible_messages(load_live_draft_chat(self.coakley, force=True)["messages"], limit=5)
                self.assertEqual(len(visible), 5)
                self.assertTrue(all(str(m.get("message_type") or "user") != "system" for m in visible))

    def test_other_league_cannot_see_messages(self) -> None:
        from live_draft_chat import append_live_draft_chat_message, load_live_draft_chat

        set_live_draft_setup_mode(self.daniel, SETUP_MODE_SHARED)
        room_a = _room(status="in_progress")
        code_a, _ = create_and_host_shared_room(self.daniel, room_a, store=self.store)
        self.daniel["live_draft_room"] = room_a
        with mock.patch("draft_room_participant_state.resolve_participant_id", return_value="user:daniel"):
            with mock.patch("draft_room_participant_state.active_participant_team", return_value="Team 1"):
                append_live_draft_chat_message(self.daniel, "Secret A")

        other = {
            AUTH_USER_ID_KEY: "user:other",
            ACTIVE_SHARED_ROOM_CODE_KEY: "ZZZZZZ",
            "live_draft_room": {"draft_room_id": "OTHER", "teams": ["X", "Y"]},
        }
        # Fabricate empty other room
        from draft_room_shared_state import shared_room_document

        self.store.save(
            shared_room_document(room_code="ZZZZZZ", host_participant_id="user:other", live_room=other["live_draft_room"])
        )
        chat = load_live_draft_chat(other, force=True)
        self.assertFalse(any("Secret A" in str(m.get("text") or "") for m in chat.get("messages") or []))
        _ = code_a


if __name__ == "__main__":
    unittest.main()
