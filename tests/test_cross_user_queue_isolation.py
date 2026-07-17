"""Daniel and Coakley11 must keep private draft queues in the same shared room."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import join_shared_draft_room
from draft_room_participant_state import (
    load_participant_workflow_into_session,
    save_participant_workflow_from_session,
)
from draft_room_shared_state import LocalFileSharedRoomStore, reset_shared_room_store_for_tests
from draft_state import DRAFT_QUEUE_KEY, add_player_to_draft_queue
from live_draft_autopick import _try_queue_auto_pick
from live_draft_queue_survival import QUEUE_SCOPE_KEY
from live_draft_setup_mode import SETUP_MODE_SHARED, finalize_shared_room_create, set_live_draft_setup_mode
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_EMAIL_KEY, AUTH_USER_ID_KEY


def _sample_room() -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Francisco Lindor", "Primary Position": "SS"},
            {"playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p3", "fullName": "Juan Soto", "Primary Position": "OF"},
        ]
    )
    return {
        "draft_room_id": "QISO1",
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


def _daniel() -> dict:
    return {
        AUTH_USER_ID_KEY: "uuid-daniel",
        AUTH_EXTERNAL_ID_KEY: "daniel",
        AUTH_USER_EMAIL_KEY: "daniel.cohen11@yahoo.com",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "daniel",
        "_suite_owned_workspace_id": "daniel",
        "draft_room_participant_id": "uuid-daniel",
        "live_draft_setup_mode": SETUP_MODE_SHARED,
    }


def _coakley() -> dict:
    return {
        AUTH_USER_ID_KEY: "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        AUTH_EXTERNAL_ID_KEY: "coakley11",
        AUTH_USER_EMAIL_KEY: "coakley11@aol.com",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "coakley11",
        "_suite_owned_workspace_id": "coakley11",
        "draft_room_participant_id": "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        "live_draft_setup_mode": SETUP_MODE_SHARED,
    }


class CrossUserQueueIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)
        self._auth = mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
        self._auth.start()

    def tearDown(self) -> None:
        self._auth.stop()
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def _bootstrap(self) -> tuple[dict, dict, str]:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(host, _sample_room(), host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        guest = _coakley()
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)
        return host, guest, code

    def test_queues_stay_private_across_add_refresh_and_autopick(self) -> None:
        host, guest, code = self._bootstrap()

        add_player_to_draft_queue(host, "Francisco Lindor")
        save_participant_workflow_from_session(host, code)
        self.assertIn("Francisco Lindor", host.get(DRAFT_QUEUE_KEY) or [])

        # Guest must not see host queue (including after hydrate / "refresh").
        load_participant_workflow_into_session(guest, code)
        self.assertEqual(guest.get(DRAFT_QUEUE_KEY) or [], [])
        self.assertNotEqual(host.get(QUEUE_SCOPE_KEY), guest.get(QUEUE_SCOPE_KEY))

        add_player_to_draft_queue(guest, "Aaron Judge")
        save_participant_workflow_from_session(guest, code)
        self.assertEqual(guest.get(DRAFT_QUEUE_KEY), ["Aaron Judge"])

        load_participant_workflow_into_session(host, code)
        self.assertEqual(host.get(DRAFT_QUEUE_KEY), ["Francisco Lindor"])
        load_participant_workflow_into_session(guest, code)
        self.assertEqual(guest.get(DRAFT_QUEUE_KEY), ["Aaron Judge"])

        # Autopick uses only the on-clock participant's private queue.
        room_a = {
            "your_team": "Team A",
            "config": {"your_team": "Team A"},
            "status": "in_progress",
        }
        available = pd.DataFrame(
            [
                {"fullName": "Francisco Lindor", "playerID": "p1"},
                {"fullName": "Aaron Judge", "playerID": "p2"},
            ]
        )
        with mock.patch("live_draft_autopick.live_draft_make_pick", return_value=(True, "ok")):
            ok_d, _ = _try_queue_auto_pick(room_a, host, available, "Team A")
            ok_c_wrong, msg_c = _try_queue_auto_pick(room_a, guest, available, "Team A")
        self.assertTrue(ok_d)
        self.assertFalse(ok_c_wrong)

        room_b = {
            "your_team": "Team B",
            "config": {"your_team": "Team B"},
            "status": "in_progress",
        }
        with mock.patch("live_draft_autopick.live_draft_make_pick", return_value=(True, "ok")):
            ok_c, _ = _try_queue_auto_pick(room_b, guest, available, "Team B")
            ok_d_wrong, _ = _try_queue_auto_pick(room_b, host, available, "Team B")
        self.assertTrue(ok_c)
        self.assertFalse(ok_d_wrong)
        _ = msg_c


class SimulatorDoesNotOverrideLiveDraftTests(unittest.TestCase):
    def test_new_live_draft_shows_pick_one_not_simulator_pick_six(self) -> None:
        from draft_actions import draft_action_context
        from draft_room_state import resolve_active_draft_source
        from live_draft_navigation import stamp_simulator_board_ownership
        from live_draft_state import analyze_live_draft_progress

        session = {
            AUTH_USER_ID_KEY: "uuid-daniel",
            AUTH_EXTERNAL_ID_KEY: "daniel",
            "_suite_active_workspace_id": "daniel",
            "room_your_team": "Team B",
            "draft_room_table": pd.DataFrame(
                [
                    {"Pick": i + 1, "Team": "Team A" if i % 2 == 0 else "Team B", "Player": f"P{i}"}
                    for i in range(6)
                ]
            ),
            "active_shared_draft_room_code": "ABC123",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            "draft_room_participant_team": "Team A",
            "live_draft_room": {
                "draft_room_id": "NEW1",
                "status": "not_started",
                "current_pick_index": 0,
                "draft_board": [],
                "teams": ["Team A", "Team B"],
                "pick_order": [
                    {"Pick": 1, "Round": 1, "Team": "Team A"},
                    {"Pick": 2, "Round": 1, "Team": "Team B"},
                ],
                "config": {"your_team": "Team A", "user_team": "Team A"},
            },
        }
        stamp_simulator_board_ownership(session, origin="programmatic_pick")
        self.assertEqual(resolve_active_draft_source(session), "live")
        progress = analyze_live_draft_progress(session["live_draft_room"])
        self.assertEqual(progress.get("current_pick"), 1)
        self.assertEqual(progress.get("on_clock_team"), "Team A")
        ctx = draft_action_context(session)
        self.assertEqual(ctx.get("active_draft_source"), "live")
        self.assertEqual(ctx.get("current_pick"), 1)
        self.assertEqual(ctx.get("on_clock_team"), "Team A")


if __name__ == "__main__":
    unittest.main()
