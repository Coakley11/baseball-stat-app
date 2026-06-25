"""Multiplayer poll propagation, timer sync, on-clock, autopick, and rec card rendering."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import (
    create_and_host_shared_room,
    join_shared_draft_room,
    poll_shared_draft_room,
)
from draft_room_shared_state import (
    SHARED_ROOM_META_KEY,
    LocalFileSharedRoomStore,
    bump_revision,
    shared_document_room_blob,
)
from live_draft_expired_pick import _multiplayer_autopick_allowed, run_expired_autopick_once
from live_draft_pick_commit import persist_applied_pick
from live_draft_pick_engine import live_draft_make_pick
from live_draft_state import LIVE_DRAFT_ROOM_KEY
from live_draft_timer_logic import live_draft_current_slot, live_draft_reset_timer, live_draft_seconds_remaining


def _sample_live_room(**overrides: object) -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Juan Soto", "Primary Position": "OF"},
        ]
    )
    base = {
        "draft_room_id": "MULTI1",
        "status": "in_progress",
        "current_pick_index": 0,
        "config": {"num_teams": 2, "your_team": "Team 1", "timer_seconds": 60, "allow_free_pool_drafting": True},
        "teams": ["Team 1", "Team 2"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team 1"},
            {"Pick": 2, "Round": 1, "Team": "Team 2"},
        ],
        "draft_board": [],
        "rosters": {"Team 1": [], "Team 2": []},
        "drafted_player_ids": [],
        "pool": pool,
        "timer_handled_index": -1,
    }
    base.update(overrides)
    return base


class SharedDocumentRoomBlobTests(unittest.TestCase):
    def test_uses_room_not_top_level_document(self) -> None:
        doc = {"revision": 2, "room_code": "ABC123", "room": {"draft_board": [{"playerID": "p1"}], "current_pick_index": 1}}
        blob = shared_document_room_blob(doc)
        self.assertIsInstance(blob, dict)
        self.assertEqual(len(blob.get("draft_board") or []), 1)


class MultiplayerPollPropagationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self.host = {"draft_room_participant_id": "host-user", "room_your_team": "Team 1"}
        self.guest = {"draft_room_participant_id": "guest-user", "room_your_team": "Team 2"}
        self._patch = mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_guest_applies_remote_pick_on_poll(self, _auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host, _sample_live_room(), store=self.store)
        ok, msg, _ = join_shared_draft_room(self.guest, code, store=self.store)
        self.assertTrue(ok, msg)

        host_room = self.host[LIVE_DRAFT_ROOM_KEY]
        row = host_room["pool"].iloc[0].to_dict()
        ok_pick, _ = live_draft_make_pick(host_room, row, verdict="Host pick")
        self.assertTrue(ok_pick)
        commit = persist_applied_pick(self.host, host_room, source="manual_pick")
        self.assertTrue(commit.ok, commit.message)

        guest_before = len(self.guest[LIVE_DRAFT_ROOM_KEY].get("draft_board") or [])
        self.assertEqual(guest_before, 0)

        changed = poll_shared_draft_room(self.guest, store=self.store)
        self.assertTrue(changed)
        guest_after = self.guest[LIVE_DRAFT_ROOM_KEY]
        self.assertEqual(len(guest_after.get("draft_board") or []), 1)
        self.assertEqual(int(guest_after.get("current_pick_index") or 0), 1)

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_on_clock_team_updates_after_remote_pick(self, _auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host, _sample_live_room(), store=self.store)
        join_shared_draft_room(self.guest, code, store=self.store)
        host_room = self.host[LIVE_DRAFT_ROOM_KEY]
        live_draft_make_pick(host_room, host_room["pool"].iloc[0].to_dict(), verdict="pick")
        persist_applied_pick(self.host, host_room, source="manual_pick")

        poll_shared_draft_room(self.guest, store=self.store)
        guest_room = self.guest[LIVE_DRAFT_ROOM_KEY]
        slot = live_draft_current_slot(guest_room)
        self.assertIsNotNone(slot)
        assert slot is not None
        self.assertEqual(slot.get("Team"), "Team 2")

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_timer_deadline_syncs_on_poll(self, _auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host, _sample_live_room(), store=self.store)
        join_shared_draft_room(self.guest, code, store=self.store)
        host_room = self.host[LIVE_DRAFT_ROOM_KEY]
        live_draft_reset_timer(host_room)
        deadline = float(host_room["timer_deadline"])
        persist_applied_pick(self.host, host_room, source="timer_reset")

        poll_shared_draft_room(self.guest, store=self.store)
        guest_room = self.guest[LIVE_DRAFT_ROOM_KEY]
        self.assertAlmostEqual(float(guest_room["timer_deadline"]), deadline, delta=1.0)
        self.assertAlmostEqual(live_draft_seconds_remaining(guest_room), live_draft_seconds_remaining(host_room), delta=2)


class HostAutopickTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self.host = {"draft_room_participant_id": "host-user", "room_your_team": "Team 1"}
        self.guest = {"draft_room_participant_id": "guest-user", "room_your_team": "Team 2"}
        self._patch = mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_host_autopicks_at_zero_and_guest_receives(self, _auth: object) -> None:
        room = _sample_live_room(timer_deadline=time.time() - 1)
        code, _ = create_and_host_shared_room(self.host, room, store=self.store)
        join_shared_draft_room(self.guest, code, store=self.store)
        host_room = self.host[LIVE_DRAFT_ROOM_KEY]
        host_room["timer_deadline"] = time.time() - 1

        self.assertTrue(_multiplayer_autopick_allowed(self.host))
        self.assertFalse(_multiplayer_autopick_allowed(self.guest))

        result = run_expired_autopick_once(self.host, host_room, source="test_autopick")
        self.assertTrue(result.ok, result.error)

        poll_shared_draft_room(self.guest, store=self.store)
        guest_room = self.guest[LIVE_DRAFT_ROOM_KEY]
        self.assertEqual(len(guest_room.get("draft_board") or []), 1)

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_guest_does_not_autopick(self, _auth: object) -> None:
        room = _sample_live_room(timer_deadline=time.time() - 1)
        code, _ = create_and_host_shared_room(self.host, room, store=self.store)
        join_shared_draft_room(self.guest, code, store=self.store)
        guest_room = self.guest[LIVE_DRAFT_ROOM_KEY]
        guest_room["timer_deadline"] = time.time() - 1
        result = run_expired_autopick_once(self.guest, guest_room, source="test_autopick")
        self.assertFalse(result.ok)
        self.assertEqual(len(guest_room.get("draft_board") or []), 0)


class RecCardRenderTests(unittest.TestCase):
    def test_recommendation_cards_use_native_streamlit_not_raw_html(self) -> None:
        from live_draft_room_ui import render_live_draft_rec_cards

        rec_df = pd.DataFrame(
            [
                {
                    "fullName": "Aaron Judge",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 12.3,
                    "Fantasy Edge": 5,
                    "Survival Probability": 0.6,
                    "Survival Label": "Likely available",
                }
            ]
        )
        st = mock.MagicMock()
        container = mock.MagicMock()
        st.columns.return_value = [container]
        st.container.return_value.__enter__ = mock.Mock(return_value=container)
        st.container.return_value.__exit__ = mock.Mock(return_value=False)

        render_live_draft_rec_cards(st, rec_df, max_cards=1)

        html_calls = [str(c) for c in st.markdown.call_args_list]
        joined = " ".join(html_calls)
        self.assertNotIn("live-rec-card", joined)
        self.assertNotIn("<div class=", joined)
        st.container.assert_called()


if __name__ == "__main__":
    unittest.main()
