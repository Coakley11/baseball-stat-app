"""Draft Lab simulation + analysis cloud/disk persistence."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from draft_lab_state import (
    DRAFT_LAB_PERSISTED_STATE_KEY,
    DRAFT_LAB_RESULT_TABS,
    hydrate_draft_lab_results_state,
    persist_draft_lab_results,
    sync_draft_lab_results_state,
)


class DraftLabPersistenceTests(unittest.TestCase):
    def test_sync_and_hydrate_roundtrip(self) -> None:
        draft = pd.DataFrame(
            [
                {"Fantasy Team": "Team A", "fullName": "Aaron Judge", "Pick": 1, "Expected Fantasy Value": 0.62},
                {"Fantasy Team": "Team B", "fullName": "Juan Soto", "Pick": 2, "Expected Fantasy Value": 0.61},
            ]
        )
        summary = pd.DataFrame(
            [
                {"Fantasy Team": "Team A", "Total Projected Fantasy Value": 8.81, "Projected Team Rank": 1},
                {"Fantasy Team": "Team B", "Total Projected Fantasy Value": 8.72, "Projected Team Rank": 2},
            ]
        )
        session: dict = {
            "draft_lab_results": {
                "draft": draft,
                "team_summary": summary,
                "strengths": pd.DataFrame(),
                "pick_analysis": pd.DataFrame(),
                "gaps": pd.DataFrame(),
                "trades": pd.DataFrame(),
                "actual_summary": pd.DataFrame(),
                "analysis_context": {"teams": ["Team A", "Team B"]},
            },
            "draft_lab_active_tab": "Team Analysis",
            "_draft_lab_team_names": ["All Teams", "Team A", "Team B"],
        }
        sync_draft_lab_results_state(session)
        blob = session.get(DRAFT_LAB_PERSISTED_STATE_KEY)
        self.assertIsInstance(blob, dict)
        self.assertEqual(blob.get("schema_version"), 2)
        self.assertEqual(blob.get("active_tab"), "Team Analysis")
        self.assertEqual(blob.get("team_names"), ["All Teams", "Team A", "Team B"])

        fresh: dict = {}
        self.assertTrue(hydrate_draft_lab_results_state(fresh, blob))
        restored = fresh.get("draft_lab_results")
        self.assertIsInstance(restored, dict)
        restored_draft = restored.get("draft")
        self.assertIsInstance(restored_draft, pd.DataFrame)
        self.assertFalse(restored_draft.empty)
        self.assertEqual(fresh.get("draft_lab_active_tab"), "Team Analysis")
        self.assertEqual(fresh.get("_draft_lab_team_names"), ["All Teams", "Team A", "Team B"])

    @patch("baseball_persistent_state.force_save_baseball_state", return_value=True)
    def test_persist_draft_lab_results_calls_force_save(self, mock_save: MagicMock) -> None:
        session: dict = {
            "draft_lab_results": {
                "draft": pd.DataFrame([{"Fantasy Team": "Team A", "Pick": 1}]),
                "team_summary": pd.DataFrame(),
                "strengths": pd.DataFrame(),
                "pick_analysis": pd.DataFrame(),
                "gaps": pd.DataFrame(),
                "trades": pd.DataFrame(),
                "actual_summary": pd.DataFrame(),
            },
            "draft_lab_active_tab": DRAFT_LAB_RESULT_TABS[2],
        }
        st_obj = MagicMock()
        persist_draft_lab_results(session, st_obj, reason="test_persist")
        mock_save.assert_called_once()
        self.assertIn(DRAFT_LAB_PERSISTED_STATE_KEY, session)


if __name__ == "__main__":
    unittest.main()
