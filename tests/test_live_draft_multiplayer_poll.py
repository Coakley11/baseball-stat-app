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
        ok, msg, _ = join_shared_draft_room(self.guest, code, requested_team="Team 2", store=self.store)
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
        join_shared_draft_room(self.guest, code, requested_team="Team 2", store=self.store)
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
        join_shared_draft_room(self.guest, code, requested_team="Team 2", store=self.store)
        host_room = self.host[LIVE_DRAFT_ROOM_KEY]
        live_draft_reset_timer(host_room)
        deadline = float(host_room["timer_deadline"])
        persist_applied_pick(self.host, host_room, source="timer_reset")

        poll_shared_draft_room(self.guest, store=self.store)
        guest_room = self.guest[LIVE_DRAFT_ROOM_KEY]
        self.assertAlmostEqual(float(guest_room["timer_deadline"]), deadline, delta=1.0)
        self.assertAlmostEqual(live_draft_seconds_remaining(guest_room), live_draft_seconds_remaining(host_room), delta=2)


class ReceiverPollApplyTests(unittest.TestCase):
    """Device B commits; Device A (passive receiver) must apply without manual refresh."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self.host = {"draft_room_participant_id": "host-user", "room_your_team": "Daniel"}
        self.guest = {"draft_room_participant_id": "guest-user", "room_your_team": "Amiel"}
        self._patch = mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    def _remote_doc_with_three_picks(self, code: str) -> None:
        doc = self.store.load(code)
        assert isinstance(doc, dict)
        room = dict(self.guest[LIVE_DRAFT_ROOM_KEY])
        board = []
        for i in range(3):
            row = room["pool"].iloc[i % len(room["pool"])].to_dict()
            pick = dict(row)
            pick["Fantasy Team"] = "Daniel" if i == 0 else "Amiel"
            board.append(pick)
        room["draft_board"] = board
        room["current_pick_index"] = 3
        room["drafted_player_ids"] = [str(p.get("playerID") or "") for p in board]
        live_draft_reset_timer(room)
        self.store.save(bump_revision(doc, live_room=room))

    def _stale_host_at_two_picks(self, code: str) -> None:
        doc = self.store.load(code)
        assert isinstance(doc, dict)
        stale_room = dict(self.host[LIVE_DRAFT_ROOM_KEY])
        board = []
        for i in range(2):
            row = stale_room["pool"].iloc[i % len(stale_room["pool"])].to_dict()
            pick = dict(row)
            pick["Fantasy Team"] = "Daniel" if i == 0 else "Amiel"
            board.append(pick)
        stale_room["draft_board"] = board
        stale_room["current_pick_index"] = 2
        self.host[LIVE_DRAFT_ROOM_KEY] = stale_room
        self.host[SHARED_ROOM_META_KEY] = {"revision": int(doc.get("revision") or 1) - 1}

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_host_applies_guest_pick_three_on_poll(self, _auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host, _sample_live_room(teams=["Daniel", "Amiel"]), store=self.store)
        join_shared_draft_room(self.guest, code, requested_team="Amiel", store=self.store)
        self._remote_doc_with_three_picks(code)
        self._stale_host_at_two_picks(code)
        self.assertEqual(len(self.host[LIVE_DRAFT_ROOM_KEY].get("draft_board") or []), 2)

        changed = poll_shared_draft_room(self.host, store=self.store)
        self.assertTrue(changed)
        host_room = self.host[LIVE_DRAFT_ROOM_KEY]
        self.assertEqual(len(host_room.get("draft_board") or []), 3)
        self.assertEqual(int(host_room.get("current_pick_index") or 0), 3)
        diag = self.host.get("_live_draft_mp_diag") or {}
        self.assertTrue(diag.get("remote_revision_applied"))

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_receiver_on_clock_team_after_pick_three(self, _auth: object) -> None:
        code, _ = create_and_host_shared_room(
            self.host,
            _sample_live_room(
                teams=["Daniel", "Amiel"],
                pick_order=[
                    {"Pick": 1, "Round": 1, "Team": "Daniel"},
                    {"Pick": 2, "Round": 1, "Team": "Amiel"},
                    {"Pick": 3, "Round": 2, "Team": "Amiel"},
                    {"Pick": 4, "Round": 2, "Team": "Daniel"},
                ],
            ),
            store=self.store,
        )
        join_shared_draft_room(self.guest, code, requested_team="Amiel", store=self.store)
        self._remote_doc_with_three_picks(code)
        self._stale_host_at_two_picks(code)
        poll_shared_draft_room(self.host, store=self.store)
        slot = live_draft_current_slot(self.host[LIVE_DRAFT_ROOM_KEY])
        assert slot is not None
        self.assertEqual(slot.get("Team"), "Daniel")

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_dirty_guard_does_not_block_newer_remote_revision(self, _auth: object) -> None:
        from live_draft_state import mark_live_draft_local_edit

        code, _ = create_and_host_shared_room(self.host, _sample_live_room(teams=["Daniel", "Amiel"]), store=self.store)
        join_shared_draft_room(self.guest, code, requested_team="Amiel", store=self.store)
        self._remote_doc_with_three_picks(code)
        self._stale_host_at_two_picks(code)
        mark_live_draft_local_edit(self.host)

        changed = poll_shared_draft_room(self.host, store=self.store)
        self.assertTrue(changed)
        self.assertEqual(len(self.host[LIVE_DRAFT_ROOM_KEY].get("draft_board") or []), 3)

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_poll_apply_rerun_allowed_after_excessive_timer_reruns(self, _auth: object) -> None:
        from live_draft_expired_pick import RERUN_LOOP_PREVENTED_KEY
        from live_draft_safe_mode import is_rerun_allowed, request_poll_apply_rerun

        code, _ = create_and_host_shared_room(self.host, _sample_live_room(), store=self.store)
        join_shared_draft_room(self.guest, code, requested_team="Team 2", store=self.store)
        self._remote_doc_with_three_picks(code)
        self._stale_host_at_two_picks(code)
        self.host["_live_draft_rerun_count"] = 20
        self.host[RERUN_LOOP_PREVENTED_KEY] = True
        self.host["_live_draft_poll_apply_pending"] = True
        allowed, _ = is_rerun_allowed(self.host, "poll_apply")
        self.assertTrue(allowed)

        st = mock.MagicMock()
        poll_shared_draft_room(self.host, store=self.store)
        self.assertTrue(request_poll_apply_rerun(st, self.host))
        st.rerun.assert_called_once()

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
        join_shared_draft_room(self.guest, code, requested_team="Team 2", store=self.store)
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
        join_shared_draft_room(self.guest, code, requested_team="Team 2", store=self.store)
        guest_room = self.guest[LIVE_DRAFT_ROOM_KEY]
        guest_room["timer_deadline"] = time.time() - 1
        result = run_expired_autopick_once(self.guest, guest_room, source="test_autopick")
        self.assertFalse(result.ok)
        self.assertEqual(len(guest_room.get("draft_board") or []), 0)


class RecCardRenderTests(unittest.TestCase):
    @mock.patch("draft_actions.resolve_manual_draft_panel_gate")
    @mock.patch("draft_actions.draft_action_context")
    @mock.patch("draft_actions._live_player_available", return_value=(True, ""))
    def test_recommendation_cards_use_compact_horizontal_layout(
        self, _avail: object, _ctx: object, gate_fn: mock.MagicMock
    ) -> None:
        from live_draft_room_ui import render_live_draft_rec_cards

        gate_fn.return_value = {"draft_enabled": True, "draft_complete": False}
        rec_df = pd.DataFrame(
            [
                {
                    "fullName": "Aaron Judge",
                    "playerID": "j1",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 12.3,
                    "Fantasy Edge": 5,
                    "Survival Probability": 0.6,
                    "Survival Label": "Likely available",
                }
            ]
        )
        st = mock.MagicMock()
        st.container.return_value.__enter__ = mock.Mock(return_value=mock.MagicMock())
        st.container.return_value.__exit__ = mock.Mock(return_value=False)
        st.columns.return_value = [mock.MagicMock(), mock.MagicMock()]
        session = {"live_draft_room": _sample_live_room_for_rec()}

        render_live_draft_rec_cards(st, session, session["live_draft_room"], rec_df, max_cards=1)

        diag = session.get("_live_draft_rec_diag") or {}
        self.assertEqual(diag.get("recommendation_card_layout_mode"), "compact_horizontal")
        md = str(st.markdown.call_args)
        self.assertIn("Aaron Judge", md)
        st.button.assert_called_once()


def _sample_live_room_for_rec() -> dict:
    return {
        "status": "in_progress",
        "current_pick_index": 0,
        "config": {"num_teams": 2, "your_team": "Team 1"},
        "teams": ["Team 1", "Team 2"],
        "pick_order": [{"Pick": 1, "Team": "Team 1"}],
        "draft_board": [],
    }


if __name__ == "__main__":
    unittest.main()
