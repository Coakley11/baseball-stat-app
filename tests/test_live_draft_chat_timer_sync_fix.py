"""Regression: Live Draft chat crash, participant dedupe, timer zero, room sync."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import create_and_host_shared_room, join_shared_draft_room, sync_shared_draft_room
from draft_room_shared_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    LocalFileSharedRoomStore,
    SHARED_ROOM_META_KEY,
    bump_revision,
    invalidate_shared_room_document_cache,
    reset_shared_room_store_for_tests,
    shared_document_room_blob,
)
from live_draft_chat import (
    CHAT_VISIBLE_LIMIT,
    append_live_draft_chat_message,
    load_live_draft_chat,
    user_visible_messages,
)
from live_draft_chat_ui import (
    CHAT_COMPOSER_KEY,
    _chat_body,
    _post_message,
    canonical_chat_participant_key,
    dedupe_chat_participant_rows,
    format_chat_participant_status_line,
    post_chat_message,
)
from live_draft_presence import JOINED_PARTICIPANTS_KEY, required_human_participant_rows
from live_draft_state import LIVE_DRAFT_ROOM_KEY
from live_draft_timer_ui import _render_timer_static
from suite_auth import AUTH_USER_ID_KEY


def _room(*, teams=None, status: str = "in_progress", pick_index: int = 0) -> dict:
    teams = teams or ["Team A", "Team B"]
    return {
        "draft_room_id": "SYNCFIX1",
        "status": status,
        "current_pick_index": pick_index,
        "config": {
            "num_teams": len(teams),
            "your_team": teams[0],
            "user_team": teams[0],
            "teams": teams,
            "timer_seconds": 10,
        },
        "teams": teams,
        "pick_order": [
            {"Pick": i + 1, "Round": 1, "Team": teams[i % len(teams)]} for i in range(6)
        ],
        "draft_board": [],
        "rosters": {t: [] for t in teams},
        "drafted_player_ids": [],
        "pool": pd.DataFrame([{"playerID": "p1", "fullName": "A", "Primary Position": "OF"}]),
        "timer_deadline": time.time() + 10,
        "timer_handled_index": -1,
    }


class ChatPostNoFragmentRerunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmp.name))
        reset_shared_room_store_for_tests(self.store)
        self.room = _room(status="not_started")
        self.daniel = {
            AUTH_USER_ID_KEY: "user:daniel",
            "draft_room_participant_id": "user:daniel",
            "room_your_team": "Team A",
            "participant_display_name": "daniel.cohen11",
            LIVE_DRAFT_ROOM_KEY: self.room,
        }
        self.coakley = {
            AUTH_USER_ID_KEY: "user:coakley11",
            "draft_room_participant_id": "user:coakley11",
            "room_your_team": "Team B",
            "participant_display_name": "coakley11",
        }
        self._patches = [
            mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False),
            mock.patch("draft_room_context.is_multiplayer_draft_active", return_value=True),
            mock.patch(
                "draft_room_participant_state.resolve_participant_id",
                side_effect=lambda s: s.get(AUTH_USER_ID_KEY) or s.get("draft_room_participant_id"),
            ),
            mock.patch(
                "draft_room_participant_state.active_participant_team",
                side_effect=lambda s: s.get("room_your_team") or "Team A",
            ),
        ]
        for p in self._patches:
            p.start()
        code, _ = create_and_host_shared_room(self.daniel, self.room, store=self.store)
        self.code = code
        join_shared_draft_room(self.coakley, code, requested_team="Team B", store=self.store)
        self.daniel[ACTIVE_SHARED_ROOM_CODE_KEY] = code
        self.daniel[LIVE_DRAFT_ROOM_KEY] = dict(self.room)
        self.coakley[ACTIVE_SHARED_ROOM_CODE_KEY] = code
        self.coakley[LIVE_DRAFT_ROOM_KEY] = dict(self.room)
        self.coakley["room_your_team"] = "Team B"

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        reset_shared_room_store_for_tests(None)
        self._tmp.cleanup()

    def test_post_message_does_not_call_fragment_rerun(self) -> None:
        st = mock.MagicMock()
        self.daniel[CHAT_COMPOSER_KEY] = "hello league"
        ok = _post_message(st, self.daniel, "hello league")
        self.assertTrue(ok)
        st.rerun.assert_not_called()
        for call in st.rerun.call_args_list:
            self.assertNotEqual((call.kwargs or {}).get("scope"), "fragment")

    def test_post_persists_and_clears_composer(self) -> None:
        self.daniel[CHAT_COMPOSER_KEY] = "pick soon"
        ok, err = post_chat_message(self.daniel, "pick soon")
        self.assertTrue(ok, err)
        self.assertEqual(self.daniel.get(CHAT_COMPOSER_KEY), "")
        chat = load_live_draft_chat(self.daniel, force=True)
        texts = [m.get("text") for m in (chat.get("messages") or [])]
        self.assertIn("pick soon", texts)

    def test_blank_and_duplicate_blocked(self) -> None:
        ok_blank, _ = append_live_draft_chat_message(self.daniel, "   ")
        self.assertFalse(ok_blank)
        ok1, err1 = append_live_draft_chat_message(self.daniel, "same line")
        self.assertTrue(ok1, err1)
        ok2, _ = append_live_draft_chat_message(self.daniel, "same line")
        self.assertFalse(ok2)

    def test_daniel_message_visible_to_coakley(self) -> None:
        ok, err = append_live_draft_chat_message(self.daniel, "shared hello")
        self.assertTrue(ok, err)
        invalidate_shared_room_document_cache(self.coakley, self.code)
        chat = load_live_draft_chat(self.coakley, force=True)
        texts = [m.get("text") for m in (chat.get("messages") or [])]
        self.assertIn("shared hello", texts)

    def test_visible_limit_five(self) -> None:
        for i in range(7):
            append_live_draft_chat_message(self.daniel, f"msg-{i}-{time.time()}")
        chat = load_live_draft_chat(self.daniel, force=True)
        visible = user_visible_messages(list(chat.get("messages") or []), limit=CHAT_VISIBLE_LIMIT)
        self.assertLessEqual(len(visible), 5)

    def test_chat_body_single_card_no_empty_wrapper(self) -> None:
        st = mock.MagicMock()
        st.form.return_value.__enter__ = mock.Mock(return_value=None)
        st.form.return_value.__exit__ = mock.Mock(return_value=False)
        st.form_submit_button.return_value = False
        st.text_area.return_value = ""
        with mock.patch("live_draft_chat_ui.refresh_live_draft_chat_if_newer"):
            with mock.patch("live_draft_chat_ui.load_live_draft_chat", return_value={"messages": [], "chat_disabled": False}):
                _chat_body(st, self.daniel)
        md_calls = [c.args[0] for c in st.markdown.call_args_list if c.args]
        card_calls = [m for m in md_calls if isinstance(m, str) and "ld-aim-root" in m]
        self.assertTrue(card_calls, "expected single AIM card markdown")
        card = card_calls[-1]
        self.assertIn("ld-aim-titlebar", card)
        self.assertIn("Live Draft Chat", card)
        # Title must come before transcript; no separate outer fixed-height wrap.
        self.assertNotIn("ld-aim-wrap", card)
        self.assertLess(card.find("ld-aim-titlebar"), card.find("ld-aim-log"))
        self.assertIn('aria-hidden="true"', card)
        self.assertNotIn("_□×", format_chat_participant_status_line(self.daniel))


class ParticipantDedupeTests(unittest.TestCase):
    def test_league_and_joined_sources_render_once(self) -> None:
        rows = [
            {"user_id": "user:daniel", "display_name": "daniel.cohen11", "team_name": "Team A", "joined": True},
            {"user_id": "user:daniel", "display_name": "daniel.cohen11", "team_name": "Team A", "joined": True},
            {"user_id": "user:coakley11", "display_name": "coakley11", "team_name": "Team B", "joined": True},
            {"user_id": "user:coakley11", "display_name": "coakley11", "team_name": "Team B", "joined": True},
        ]
        out = dedupe_chat_participant_rows(rows)
        self.assertEqual(len(out), 2)
        line = " · ".join(
            f"{r['display_name']} ({r['team_name']})" for r in out
        )
        self.assertEqual(line, "daniel.cohen11 (Team A) · coakley11 (Team B)")

    def test_email_and_user_id_merge_by_team(self) -> None:
        rows = [
            {"user_id": "user:daniel", "display_name": "daniel.cohen11", "team_name": "Team A"},
            {
                "user_id": "daniel.cohen11@example.com",
                "display_name": "daniel.cohen11@example.com",
                "team_name": "Team A",
            },
        ]
        out = dedupe_chat_participant_rows(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(canonical_chat_participant_key(out[0]), "user:daniel")

    def test_distinct_users_both_render(self) -> None:
        out = dedupe_chat_participant_rows(
            [
                {"user_id": "user:a", "display_name": "A", "team_name": "Team A"},
                {"user_id": "user:b", "display_name": "B", "team_name": "Team B"},
            ]
        )
        self.assertEqual(len(out), 2)

    def test_blank_records_ignored(self) -> None:
        out = dedupe_chat_participant_rows([{}, {"user_id": "", "display_name": "", "team_name": ""}])
        self.assertEqual(out, [])

    def test_missing_display_name_fallback(self) -> None:
        out = dedupe_chat_participant_rows([{"user_id": "user:x", "team_name": "Team A"}])
        self.assertEqual(out[0]["display_name"], "user:x")

    def test_required_rows_dedupe_participants_plus_joined(self) -> None:
        session = {AUTH_USER_ID_KEY: "user:daniel", ACTIVE_SHARED_ROOM_CODE_KEY: "X"}
        room = _room(status="not_started")
        doc = {
            "participants": {
                "user:daniel": {"assigned_team": "Team A", "display_name": "daniel.cohen11", "joined_at": "t0"},
                "email:daniel": {
                    "user_id": "user:daniel",
                    "assigned_team": "Team A",
                    "display_name": "daniel.cohen11",
                    "joined_at": "t0",
                },
                "user:coakley11": {"assigned_team": "Team B", "display_name": "coakley11", "joined_at": "t1"},
            },
            JOINED_PARTICIPANTS_KEY: {
                "user:daniel": {
                    "user_id": "user:daniel",
                    "display_name": "daniel.cohen11",
                    "team_name": "Team A",
                    "joined_at": "t0",
                },
                "user:coakley11": {
                    "user_id": "user:coakley11",
                    "display_name": "coakley11",
                    "team_name": "Team B",
                    "joined_at": "t1",
                },
            },
            "host_user_id": "user:daniel",
        }
        rows = required_human_participant_rows(session, room, document=doc)
        self.assertEqual(len(rows), 2)
        session["live_draft_room"] = room
        with mock.patch("draft_room_shared_state.load_shared_room", return_value=doc):
            line = format_chat_participant_status_line(session)
        self.assertEqual(line.count("daniel.cohen11"), 1)
        self.assertEqual(line.count("coakley11"), 1)
        self.assertNotIn(" ·  · ", line)


class TimerZeroAndRevisionSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmp.name))
        reset_shared_room_store_for_tests(self.store)
        self.host = {
            AUTH_USER_ID_KEY: "user:daniel",
            "draft_room_participant_id": "user:daniel",
            "room_your_team": "Team A",
        }
        self.guest = {
            AUTH_USER_ID_KEY: "user:coakley11",
            "draft_room_participant_id": "user:coakley11",
            "room_your_team": "Team B",
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

    def test_expired_timer_shows_zero_without_duplicate_auto_picking(self) -> None:
        st = mock.MagicMock()
        room = _room(pick_index=0)
        room["timer_deadline"] = time.time() - 1
        session: dict = {LIVE_DRAFT_ROOM_KEY: room}
        _render_timer_static(st, session, room, source="static")
        md = " ".join(str(c.args[0]) for c in st.markdown.call_args_list if c.args)
        # Timer bar owns countdown only — Auto-picking lives under On-the-Clock.
        self.assertNotIn("Auto-picking", md)
        self.assertTrue(session.get("_live_draft_timer_autopick_ui"))
        self.assertIn("0s", md)

    def test_guest_discards_stale_revision(self) -> None:
        code, _doc = create_and_host_shared_room(self.host, _room(), store=self.store)
        join_shared_draft_room(self.guest, code, requested_team="Team B", store=self.store)
        remote = self.store.load(code)
        assert remote is not None
        remote["revision"] = 10
        blob = dict(shared_document_room_blob(remote) or {})
        blob["current_pick_index"] = 0
        blob["status"] = "in_progress"
        blob["draft_board"] = []
        blob["timer_deadline"] = time.time() + 10
        remote["room"] = blob
        self.store.save(remote)

        next_deadline = time.time() + 9
        # Advance pick with a matching board row so repair_stale_live_draft_progress
        # does not snap the index back to len(draft_board).
        advanced_room = {
            **blob,
            "current_pick_index": 1,
            "timer_deadline": next_deadline,
            "status": "in_progress",
            "draft_board": [
                {
                    "Pick": 1,
                    "Round": 1,
                    "Team": "Team A",
                    "playerID": "p1",
                    "fullName": "A",
                }
            ],
            "drafted_player_ids": ["p1"],
        }
        advanced = bump_revision(remote, live_room=advanced_room)
        self.assertEqual(int(advanced.get("revision") or 0), 11)
        stored_blob = shared_document_room_blob(advanced) or {}
        self.assertEqual(int(stored_blob.get("current_pick_index")), 1)
        self.store.save(advanced)

        # Guest still cached at rev 10 / pick 0.
        self.guest[ACTIVE_SHARED_ROOM_CODE_KEY] = code
        self.guest[SHARED_ROOM_META_KEY] = {"revision": 10, "room_code": code}
        self.guest[LIVE_DRAFT_ROOM_KEY] = {
            **blob,
            "current_pick_index": 0,
            "timer_deadline": time.time() + 10,
            "draft_board": [],
        }
        invalidate_shared_room_document_cache(self.guest, code)
        changed = sync_shared_draft_room(self.guest, force=True, store=self.store)
        self.assertTrue(changed)
        runtime = self.guest.get(LIVE_DRAFT_ROOM_KEY) or {}
        self.assertEqual(int((self.guest.get(SHARED_ROOM_META_KEY) or {}).get("revision") or 0), 11)
        self.assertEqual(int(runtime.get("current_pick_index")), 1)
        self.assertEqual(len(runtime.get("draft_board") or []), 1)
        self.assertAlmostEqual(float(runtime.get("timer_deadline") or 0), next_deadline, delta=1.0)

    def test_stale_guest_save_cannot_overwrite_newer_host(self) -> None:
        code, doc = create_and_host_shared_room(self.host, _room(), store=self.store)
        join_shared_draft_room(self.guest, code, requested_team="Team B", store=self.store)
        current = self.store.load(code)
        assert current is not None
        head = int(current.get("revision") or 1)
        newer = bump_revision(current, live_room=_room(pick_index=2))
        self.store.save(newer)
        newer_rev = int((self.store.load(code) or {}).get("revision") or 0)
        stale = bump_revision({**current, "revision": head}, live_room=_room(pick_index=0))
        ok, saved = self.store.save_if_revision(stale, expected_revision=head)
        self.assertFalse(ok)
        latest = self.store.load(code)
        assert latest is not None
        self.assertEqual(int(latest.get("revision") or 0), newer_rev)
        blob = shared_document_room_blob(latest) or {}
        self.assertEqual(int(blob.get("current_pick_index") or -1), 2)


if __name__ == "__main__":
    unittest.main()
