"""Tests for Live Draft runtime diagnostic table."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_room_runtime_diagnostics import (
    capture_leave_state_after,
    capture_leave_state_before,
    get_runtime_diagnostic_rows,
    record_scoring_pipeline_stage,
    resolve_displayed_team_label,
)


class DraftRoomRuntimeDiagnosticsTests(unittest.TestCase):
    def test_resolve_displayed_team_label_prefers_participant_team_in_mp(self) -> None:
        session = {
            "active_shared_draft_room_code": "ABC123",
            "draft_room_participant_id": "guest-1",
            "draft_room_participant_team": "Team 2",
            "draft_room_participant_membership": {
                "ABC123": {"guest-1": {"participant_id": "guest-1", "assigned_team": "Team 2"}}
            },
            "live_draft_room": {
                "config": {"user_team": "Team Daniel"},
                "teams": ["Team Daniel", "Team 2"],
            },
            "room_your_team": "Daniel",
        }
        label, source = resolve_displayed_team_label(session)
        self.assertEqual(label, "Team 2")
        self.assertEqual(source, "active_participant_team")

    def test_identity_skips_mp_team_until_room_joined(self) -> None:
        session = {
            "draft_room_participant_id": "guest-1",
            "room_your_team": "Daniel",
            "global_fantasy_settings": {"room_your_team": "Daniel"},
        }
        try:
            from global_fantasy_settings_state import GLOBAL_TEAM_KEY

            session[GLOBAL_TEAM_KEY] = "Daniel"
        except ImportError:
            pass
        rows = dict((b, c) for a, b, c in get_runtime_diagnostic_rows(session) if a == "Identity")
        self.assertEqual(rows.get("multiplayer_joined"), "False")
        self.assertEqual(rows.get("assigned_team"), "—")
        self.assertEqual(rows.get("displayed_team_label"), "Daniel")

    def test_leave_trace_captured(self) -> None:
        session = {
            "active_shared_draft_room_code": "ABC123",
            "draft_room_participant_team": "Team 2",
            "draft_room_participant_id": "guest-1",
        }
        capture_leave_state_before(session)
        session.pop("active_shared_draft_room_code", None)
        capture_leave_state_after(session, membership_marked_left=True)
        rows = dict((f"{a}.{b}", c) for a, b, c in get_runtime_diagnostic_rows(session) if a.startswith("Leave"))
        self.assertIn("Leave (before).active_shared_draft_room_code", rows)
        self.assertEqual(rows["Leave (before).active_shared_draft_room_code"], "ABC123")
        self.assertEqual(rows.get("Leave (after).active_shared_draft_room_code"), "—")

    def test_scoring_pipeline_records_stages(self) -> None:
        session: dict = {}
        pool = pd.DataFrame(
            [
                {
                    "fullName": "Aaron Judge",
                    "Expected Fantasy Value": 0.95,
                    "Model Rank": 3,
                    "Market Rank": 8,
                    "Fantasy Edge": 5,
                    "ADP Rank": 8,
                }
            ]
        )
        record_scoring_pipeline_stage(session, "original_source", pool)
        record_scoring_pipeline_stage(session, "displayed", pool)
        rows = get_runtime_diagnostic_rows(session)
        labels = [f"{sec}.{field}" for sec, field, _ in rows if sec == "Scoring Aaron Judge"]
        self.assertTrue(any("original_source.Model Rank" in x for x in labels))
        self.assertTrue(any("displayed.Model Rank" in x for x in labels))


if __name__ == "__main__":
    unittest.main()
