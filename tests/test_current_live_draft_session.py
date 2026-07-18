"""Current Live Draft session must supersede stale completed-room restore pointers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from draft_room_participant_state import (
    ACTIVE_PARTICIPANT_TEAM_KEY,
    ACTIVE_SHARED_ROOM_CODE_KEY,
    MEMBERSHIP_KEY,
    PARTICIPANT_STATE_KEY,
    bind_current_live_draft_session,
    participant_has_left_room,
    restore_persisted_shared_room_membership,
    set_active_participant,
)
from live_draft_navigation import _try_hydrate_shared_room


class CurrentLiveDraftSessionTests(unittest.TestCase):
    def test_bind_marks_old_membership_left(self) -> None:
        session = {
            ACTIVE_SHARED_ROOM_CODE_KEY: "AASEN5",
            ACTIVE_PARTICIPANT_TEAM_KEY: "Team 2",
            "live_draft_room": {
                "status": "complete",
                "sync": {"room_code": "AASEN5"},
                "config": {"your_team": "Team 2"},
                "teams": ["Team 1", "Team 2"],
            },
            "live_draft_my_team": "Team 2",
            MEMBERSHIP_KEY: {
                "AASEN5": {"pid-a": {"participant_id": "pid-a", "assigned_team": "Team 2"}},
                "NEWRM1": {"pid-a": {"participant_id": "pid-a", "assigned_team": "Team Y"}},
            },
            PARTICIPANT_STATE_KEY: {
                "AASEN5": {"by_participant": {"pid-a": {"participant_id": "pid-a", "joined_at": "2026-07-01T00:00:00+00:00"}}},
                "NEWRM1": {"by_participant": {"pid-a": {"participant_id": "pid-a", "joined_at": "2026-07-14T00:00:00+00:00"}}},
            },
        }
        with patch(
            "draft_room_participant_state.resolve_participant_id",
            return_value="pid-a",
        ):
            bind_current_live_draft_session(session, "NEWRM1", assigned_team="Team Y")
            self.assertEqual(session.get(ACTIVE_SHARED_ROOM_CODE_KEY), "NEWRM1")
            self.assertEqual(session.get(ACTIVE_PARTICIPANT_TEAM_KEY), "Team Y")
            self.assertTrue(participant_has_left_room(session, "AASEN5"))
            self.assertFalse(participant_has_left_room(session, "NEWRM1"))
            self.assertNotIn("live_draft_room", session)

    def test_set_active_participant_supersedes_old_room(self) -> None:
        session = {
            ACTIVE_SHARED_ROOM_CODE_KEY: "AASEN5",
            MEMBERSHIP_KEY: {
                "AASEN5": {"pid-a": {"participant_id": "pid-a", "assigned_team": "Team 2"}},
            },
            PARTICIPANT_STATE_KEY: {},
            "live_draft_room": {"sync": {"room_code": "AASEN5"}, "status": "in_progress"},
        }
        with patch(
            "draft_room_participant_state.resolve_participant_id",
            return_value="pid-a",
        ):
            set_active_participant(
                session,
                room_code="NEWRM1",
                participant_id="pid-a",
                assigned_team="Team Y",
            )
            self.assertEqual(session.get(ACTIVE_SHARED_ROOM_CODE_KEY), "NEWRM1")
            self.assertTrue(participant_has_left_room(session, "AASEN5"))

    def test_restore_prefers_active_league_source_over_stale_aasen(self) -> None:
        session = {
            ACTIVE_SHARED_ROOM_CODE_KEY: "AASEN5",
            ACTIVE_PARTICIPANT_TEAM_KEY: "Team 2",
            "live_draft_room": {"sync": {"room_code": "AASEN5"}, "status": "complete"},
            MEMBERSHIP_KEY: {
                "AASEN5": {"pid-a": {"participant_id": "pid-a", "assigned_team": "Team 2"}},
                "NEWRM1": {"pid-a": {"participant_id": "pid-a", "assigned_team": "Team Y"}},
            },
            PARTICIPANT_STATE_KEY: {
                "AASEN5": {
                    "by_participant": {
                        "pid-a": {"participant_id": "pid-a", "joined_at": "2026-07-01T00:00:00+00:00"}
                    }
                },
                "NEWRM1": {
                    "by_participant": {
                        "pid-a": {"participant_id": "pid-a", "joined_at": "2026-07-14T00:00:00+00:00"}
                    }
                },
            },
        }
        active_ctx = {
            "my_team_name": "Team Y",
            "metadata": {"league_id": "league:xy", "source_room_code": "NEWRM1"},
            "team_ownership": {
                "Team Y": {"user_id": "user:coakley11", "claim_status": "claimed"},
            },
        }
        with (
            patch("draft_room_participant_state.resolve_participant_id", return_value="pid-a"),
            patch(
                "draft_room_create_verify.is_plausible_share_code",
                side_effect=lambda c: bool(c) and len(str(c)) >= 5,
            ),
            patch(
                "fantasy_league_context.get_active_league_context",
                return_value=active_ctx,
            ),
            patch(
                "fantasy_league_team_ownership.resolve_account_fantasy_team",
                return_value="Team Y",
            ),
            patch("suite_auth.is_auth_enabled", return_value=False),
            patch(
                "shared_room_membership_gate.load_authoritative_shared_document",
                return_value={
                    "room_code": "NEWRM1",
                    "status": "in_progress",
                    "draft_room_id": "dr-new",
                    "participants": {"pid-a": {"assigned_team": "Team Y"}},
                    "room": {"status": "in_progress", "draft_room_id": "dr-new"},
                },
            ),
        ):
            code = restore_persisted_shared_room_membership(session)
        self.assertEqual(code, "NEWRM1")
        self.assertEqual(session.get(ACTIVE_SHARED_ROOM_CODE_KEY), "NEWRM1")
        self.assertTrue(participant_has_left_room(session, "AASEN5"))

    def test_hydrate_ignores_mismatched_local_room(self) -> None:
        session = {
            "live_draft_room": {
                "status": "in_progress",
                "sync": {"room_code": "AASEN5"},
                "teams": ["Team 1", "Team 2"],
            },
            ACTIVE_SHARED_ROOM_CODE_KEY: "NEWRM1",
        }
        with patch(
            "draft_room_shared_state.load_shared_room",
            return_value={
                "room_code": "NEWRM1",
                "live_draft": {
                    "status": "in_progress",
                    "sync": {"room_code": "NEWRM1"},
                    "teams": ["Team X", "Team Y"],
                    "draft_room_id": "NEWRM1",
                    "pick_order": [],
                },
            },
        ), patch(
            "live_draft_state.room_from_persist_dict",
            side_effect=lambda blob: blob,
        ):
            room = _try_hydrate_shared_room(session, "NEWRM1")
        self.assertIsInstance(room, dict)
        self.assertEqual((room.get("sync") or {}).get("room_code"), "NEWRM1")
        self.assertEqual(session.get(ACTIVE_SHARED_ROOM_CODE_KEY), "NEWRM1")


if __name__ == "__main__":
    unittest.main()
