"""Live Draft Chat — persist without bumping board revision."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from draft_room_shared_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    LocalFileSharedRoomStore,
    preserve_shared_room_chat,
    reset_shared_room_store_for_tests,
    shared_room_document,
)
from live_draft_chat import (
    append_live_draft_chat_message,
    format_chat_timestamp,
    load_live_draft_chat,
    message_mentions_viewer,
    normalize_chat_payload,
    set_chat_disabled,
    unread_chat_count,
)


def _minimal_live_room() -> dict:
    return {
        "status": "in_progress",
        "teams": ["Team X", "Team Y"],
        "draft_board": [],
        "current_pick_index": 0,
        "draft_room_id": "CHAT01",
        "meta": {},
    }


class LiveDraftChatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmp.name))
        reset_shared_room_store_for_tests(self.store)
        doc = shared_room_document(
            room_code="CHAT01",
            host_participant_id="host1",
            live_room=_minimal_live_room(),
            revision=3,
        )
        self.store.save(doc)
        self.session = {
            ACTIVE_SHARED_ROOM_CODE_KEY: "CHAT01",
            "live_draft_room": _minimal_live_room(),
            "participant_display_name": "Daniel",
        }

    def tearDown(self) -> None:
        reset_shared_room_store_for_tests(None)
        self._tmp.cleanup()

    def test_append_does_not_bump_board_revision(self) -> None:
        with mock.patch("draft_room_context.is_multiplayer_draft_active", return_value=True):
            with mock.patch(
                "draft_room_participant_state.resolve_participant_id",
                return_value="p1",
            ):
                with mock.patch(
                    "draft_room_participant_state.active_participant_team",
                    return_value="Team X",
                ):
                    ok, err = append_live_draft_chat_message(self.session, "Who's drafting next?")
        self.assertTrue(ok, err)
        doc = self.store.load("CHAT01")
        assert doc is not None
        self.assertEqual(int(doc.get("revision") or 0), 3)
        chat = normalize_chat_payload(doc.get("chat"))
        self.assertEqual(int(chat.get("chat_revision") or 0), 1)
        self.assertEqual(len(chat.get("messages") or []), 1)
        self.assertIn("drafting", chat["messages"][0]["text"])
        self.assertEqual(chat["messages"][0]["claimed_team"], "Team X")
        self.assertEqual(chat["messages"][0]["message_type"], "user")

    def test_duplicate_submission_rejected(self) -> None:
        with mock.patch("draft_room_context.is_multiplayer_draft_active", return_value=True):
            with mock.patch(
                "draft_room_participant_state.resolve_participant_id",
                return_value="p1",
            ):
                with mock.patch(
                    "draft_room_participant_state.active_participant_team",
                    return_value="Team X",
                ):
                    ok1, _ = append_live_draft_chat_message(self.session, "Hello league")
                    ok2, err2 = append_live_draft_chat_message(self.session, "Hello league")
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertIn("Duplicate", err2)

    def test_eastern_timestamp_suffix(self) -> None:
        label = format_chat_timestamp("2026-07-17T18:30:00Z")
        self.assertTrue(label.endswith("ET"))

    def test_mention_highlight_for_viewer_team(self) -> None:
        msg = {"text": "Hey @Team X are you ready?", "message_type": "user"}
        with mock.patch(
            "live_draft_chat._resolve_author",
            return_value=("p1", "Daniel", "Team X"),
        ):
            self.assertTrue(message_mentions_viewer(msg, self.session))

    def test_unread_count_when_collapsed(self) -> None:
        with mock.patch("draft_room_context.is_multiplayer_draft_active", return_value=True):
            with mock.patch(
                "draft_room_participant_state.resolve_participant_id",
                return_value="p1",
            ):
                with mock.patch(
                    "draft_room_participant_state.active_participant_team",
                    return_value="Team X",
                ):
                    append_live_draft_chat_message(self.session, "New note")
        self.session["_live_draft_chat_last_seen_rev"] = 0
        self.assertGreaterEqual(unread_chat_count(self.session), 1)

    def test_board_save_preserves_newer_chat(self) -> None:
        with mock.patch("draft_room_context.is_multiplayer_draft_active", return_value=True):
            with mock.patch(
                "draft_room_participant_state.resolve_participant_id",
                return_value="p1",
            ):
                with mock.patch(
                    "draft_room_participant_state.active_participant_team",
                    return_value="Team X",
                ):
                    append_live_draft_chat_message(self.session, "Keep this message")

        stale = self.store.load("CHAT01")
        assert stale is not None
        stale = dict(stale)
        stale.pop("chat", None)
        stale["revision"] = 4
        saved = self.store.save(stale)
        chat = normalize_chat_payload(saved.get("chat"))
        self.assertGreaterEqual(int(chat.get("chat_revision") or 0), 1)
        self.assertTrue(any("Keep this" in str(m.get("text") or "") for m in chat.get("messages") or []))

    def test_preserve_shared_room_chat_prefers_higher_revision(self) -> None:
        outgoing = {"room_code": "X", "chat": {"chat_revision": 1, "messages": []}}
        existing = {
            "chat": {
                "chat_revision": 4,
                "messages": [{"id": "a", "text": "hi", "display_name": "A", "ts": "t", "team": "", "participant_id": ""}],
            }
        }
        merged = preserve_shared_room_chat(outgoing, existing)
        self.assertEqual(int(merged["chat"]["chat_revision"]), 4)
        self.assertEqual(merged["chat"]["messages"][0]["text"], "hi")

    def test_load_uses_session_cache(self) -> None:
        with mock.patch("draft_room_context.is_multiplayer_draft_active", return_value=True):
            with mock.patch(
                "draft_room_participant_state.resolve_participant_id",
                return_value="p1",
            ):
                with mock.patch(
                    "draft_room_participant_state.active_participant_team",
                    return_value="Team X",
                ):
                    append_live_draft_chat_message(self.session, "Cached hello")
        chat = load_live_draft_chat(self.session, force=False)
        self.assertEqual(chat["messages"][-1]["text"], "Cached hello")

    def test_commissioner_can_disable_chat(self) -> None:
        with mock.patch("live_draft_chat.is_chat_commissioner", return_value=True):
            with mock.patch("draft_room_context.is_multiplayer_draft_active", return_value=True):
                ok, err = set_chat_disabled(self.session, True)
        self.assertTrue(ok, err)
        chat = load_live_draft_chat(self.session, force=True)
        self.assertTrue(chat.get("chat_disabled"))


if __name__ == "__main__":
    unittest.main()
