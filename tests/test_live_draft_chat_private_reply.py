"""Phase 2B.1 — direct private replies with authoritative visibility."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from draft_room_shared_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    LocalFileSharedRoomStore,
    reset_shared_room_store_for_tests,
    shared_room_document,
)
from live_draft_chat import (
    MSG_TYPE_PRIVATE_REPLY,
    VISIBILITY_PRIVATE,
    append_live_draft_chat_message,
    append_private_reply,
    find_chat_message_in_room,
    load_live_draft_chat,
    mark_chat_seen,
    participant_may_view_message,
    query_visible_chat_messages,
    unread_chat_count,
)


def _minimal_live_room() -> dict:
    return {
        "status": "in_progress",
        "teams": ["Team A", "Team B", "Team C"],
        "draft_board": [],
        "current_pick_index": 0,
        "draft_room_id": "PRIV01",
        "meta": {},
    }


class PrivateReplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmp.name))
        reset_shared_room_store_for_tests(self.store)
        doc = shared_room_document(
            room_code="PRIV01",
            host_participant_id="daniel-pid",
            live_room=_minimal_live_room(),
            revision=1,
        )
        doc["commissioner_participant_id"] = "daniel-pid"
        doc["participants"] = {
            "daniel-pid": {"participant_id": "daniel-pid", "display_name": "Daniel", "team": "Team A"},
            "coakley-pid": {"participant_id": "coakley-pid", "display_name": "Coakley11", "team": "Team B"},
            "third-pid": {"participant_id": "third-pid", "display_name": "Third", "team": "Team C"},
        }
        self.store.save(doc)
        self.daniel = {
            ACTIVE_SHARED_ROOM_CODE_KEY: "PRIV01",
            "live_draft_room": _minimal_live_room(),
            "participant_display_name": "Daniel",
            "draft_room_participant_id": "daniel-pid",
        }
        self.coakley = {
            ACTIVE_SHARED_ROOM_CODE_KEY: "PRIV01",
            "live_draft_room": _minimal_live_room(),
            "participant_display_name": "Coakley11",
            "draft_room_participant_id": "coakley-pid",
        }
        self.third = {
            ACTIVE_SHARED_ROOM_CODE_KEY: "PRIV01",
            "live_draft_room": _minimal_live_room(),
            "participant_display_name": "Third",
            "draft_room_participant_id": "third-pid",
        }

    def tearDown(self) -> None:
        reset_shared_room_store_for_tests(None)
        self._tmp.cleanup()

    def _patch_identity(self, session: dict, pid: str, team: str):
        return mock.patch.multiple(
            "live_draft_chat",
            _is_authenticated_league_session=mock.Mock(return_value=True),
            _resolve_author=mock.Mock(return_value=(pid, session["participant_display_name"], team)),
            _participant_still_in_room=mock.Mock(return_value=True),
        )

    def test_private_reply_visibility_and_unread(self) -> None:
        with self._patch_identity(self.daniel, "daniel-pid", "Team A"):
            ok, err = append_live_draft_chat_message(
                self.daniel, "Are you taking a pitcher here?"
            )
        self.assertTrue(ok, err)
        public = load_live_draft_chat(self.daniel, force=True)
        public_id = str(public["messages"][0]["id"])

        mark_chat_seen(self.daniel)
        mark_chat_seen(self.coakley)
        mark_chat_seen(self.third)

        with self._patch_identity(self.coakley, "coakley-pid", "Team B"):
            ok2, err2 = append_private_reply(
                self.coakley,
                reply_to_message_id=public_id,
                text="Yes, probably with my next pick.",
                client_message_id="client-reply-1",
            )
        self.assertTrue(ok2, err2)

        with self._patch_identity(self.daniel, "daniel-pid", "Team A"):
            daniel_msgs = query_visible_chat_messages(self.daniel, force=True)
        with self._patch_identity(self.coakley, "coakley-pid", "Team B"):
            coakley_msgs = query_visible_chat_messages(self.coakley, force=True)
        with self._patch_identity(self.third, "third-pid", "Team C"):
            third_msgs = query_visible_chat_messages(self.third, force=True)

        private_d = [m for m in daniel_msgs if m.get("message_type") == MSG_TYPE_PRIVATE_REPLY]
        private_c = [m for m in coakley_msgs if m.get("message_type") == MSG_TYPE_PRIVATE_REPLY]
        private_t = [m for m in third_msgs if m.get("message_type") == MSG_TYPE_PRIVATE_REPLY]
        self.assertEqual(len(private_d), 1)
        self.assertEqual(len(private_c), 1)
        self.assertEqual(len(private_t), 0)
        self.assertEqual(private_d[0]["visibility"], VISIBILITY_PRIVATE)
        self.assertEqual(private_d[0]["reply_to_preview"], "Are you taking a pitcher here?")
        self.assertEqual(private_d[0]["recipient_participant_id"], "daniel-pid")
        self.assertEqual(private_d[0]["sender_participant_id"], "coakley-pid")

        # Third cannot view even if handed the raw row.
        self.assertFalse(participant_may_view_message(private_d[0], "third-pid"))

        # Unread: recipient only.
        with self._patch_identity(self.daniel, "daniel-pid", "Team A"):
            self.assertEqual(unread_chat_count(self.daniel), 1)
        with self._patch_identity(self.coakley, "coakley-pid", "Team B"):
            self.assertEqual(unread_chat_count(self.coakley), 0)

        # Persist after "refresh".
        with self._patch_identity(self.daniel, "daniel-pid", "Team A"):
            again = load_live_draft_chat(self.daniel, force=True)
        self.assertEqual(
            len([m for m in again["messages"] if m.get("message_type") == MSG_TYPE_PRIVATE_REPLY]),
            1,
        )

        # Idempotent client id.
        with self._patch_identity(self.coakley, "coakley-pid", "Team B"):
            ok3, _ = append_private_reply(
                self.coakley,
                reply_to_message_id=public_id,
                text="Yes, probably with my next pick.",
                client_message_id="client-reply-1",
            )
        self.assertTrue(ok3)
        doc = self.store.load("PRIV01")
        chat = (doc or {}).get("chat") or {}
        privates = [
            m
            for m in (chat.get("messages") or [])
            if str(m.get("message_type") or "") == MSG_TYPE_PRIVATE_REPLY
        ]
        self.assertEqual(len(privates), 1)

    def test_private_reply_cannot_cross_rooms(self) -> None:
        with self._patch_identity(self.daniel, "daniel-pid", "Team A"):
            ok, err = append_live_draft_chat_message(self.daniel, "Room one message")
        self.assertTrue(ok, err)
        mid = load_live_draft_chat(self.daniel, force=True)["messages"][0]["id"]

        other = shared_room_document(
            room_code="PRIV02",
            host_participant_id="daniel-pid",
            live_room=_minimal_live_room(),
            revision=1,
        )
        self.store.save(other)
        self.coakley[ACTIVE_SHARED_ROOM_CODE_KEY] = "PRIV02"
        with self._patch_identity(self.coakley, "coakley-pid", "Team B"):
            ok2, err2 = append_private_reply(
                self.coakley,
                reply_to_message_id=mid,
                text="Leak attempt",
                client_message_id="cross-room",
            )
        self.assertFalse(ok2)
        self.assertIn("not found", (err2 or "").lower())

    def test_deleted_room_private_replies_do_not_restore(self) -> None:
        with self._patch_identity(self.daniel, "daniel-pid", "Team A"):
            append_live_draft_chat_message(self.daniel, "Hello")
        mid = load_live_draft_chat(self.daniel, force=True)["messages"][0]["id"]
        with self._patch_identity(self.coakley, "coakley-pid", "Team B"):
            append_private_reply(
                self.coakley,
                reply_to_message_id=mid,
                text="Secret",
                client_message_id="del-1",
            )
        self.store.delete("PRIV01") if hasattr(self.store, "delete") else None
        # Soft-delete / wipe document.
        root = Path(self._tmp.name)
        for path in root.rglob("*PRIV01*"):
            if path.is_file():
                path.unlink()
        self.daniel.pop("_live_draft_chat_cache", None)
        with self._patch_identity(self.daniel, "daniel-pid", "Team A"):
            chat = load_live_draft_chat(self.daniel, force=True)
        self.assertEqual(chat.get("messages") or [], [])

    def test_cannot_privately_reply_to_self(self) -> None:
        with self._patch_identity(self.daniel, "daniel-pid", "Team A"):
            ok, err = append_live_draft_chat_message(self.daniel, "My own note")
        self.assertTrue(ok, err)
        mid = load_live_draft_chat(self.daniel, force=True)["messages"][0]["id"]
        with self._patch_identity(self.daniel, "daniel-pid", "Team A"):
            ok2, err2 = append_private_reply(
                self.daniel,
                reply_to_message_id=mid,
                text="Talking to myself",
                client_message_id="self-reply",
            )
        self.assertFalse(ok2)
        self.assertIn("own message", (err2 or "").lower())

    def test_third_cannot_retrieve_private_via_query_apis(self) -> None:
        with self._patch_identity(self.daniel, "daniel-pid", "Team A"):
            ok, err = append_live_draft_chat_message(self.daniel, "Public ask")
        self.assertTrue(ok, err)
        public_id = load_live_draft_chat(self.daniel, force=True)["messages"][0]["id"]
        with self._patch_identity(self.coakley, "coakley-pid", "Team B"):
            ok2, err2 = append_private_reply(
                self.coakley,
                reply_to_message_id=public_id,
                text="Private answer",
                client_message_id="auth-query-1",
            )
        self.assertTrue(ok2, err2)
        with self._patch_identity(self.coakley, "coakley-pid", "Team B"):
            privates = [
                m
                for m in query_visible_chat_messages(self.coakley, force=True)
                if m.get("message_type") == MSG_TYPE_PRIVATE_REPLY
            ]
        self.assertEqual(len(privates), 1)
        private_id = str(privates[0].get("id") or "")

        with self._patch_identity(self.third, "third-pid", "Team C"):
            third_msgs = query_visible_chat_messages(self.third, force=True)
            third_private = [m for m in third_msgs if m.get("message_type") == MSG_TYPE_PRIVATE_REPLY]
            self.assertEqual(third_private, [])
            # Direct lookup must also deny unauthorized retrieval.
            self.assertIsNone(find_chat_message_in_room(self.third, private_id))
            loaded = load_live_draft_chat(self.third, force=True)
            self.assertFalse(
                any(str(m.get("id") or "") == private_id for m in (loaded.get("messages") or []))
            )


if __name__ == "__main__":
    unittest.main()
