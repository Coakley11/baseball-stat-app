"""Activity write/read namespace parity between Baseball and Command Center."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from suite_activity_namespace import (
    ACTIVITY_APP_ALIASES,
    build_activity_write_diagnostics,
    normalize_activity_app_key,
    stamp_activity_metrics,
)


class TestSuiteActivityNamespace(unittest.TestCase):
    def test_baseball_app_aliases_normalize(self) -> None:
        for raw in ("baseball-stat-app", "Baseball Analytics", "baseball"):
            self.assertEqual(normalize_activity_app_key(raw), "baseball")

    @patch("suite_workspace.scoped_cloud_app_id", return_value="baseball__daniel")
    @patch("suite_workspace.workspace_storage_app_keys", return_value={"baseball__daniel"})
    @patch("suite_workspace.get_active_workspace_id", return_value="daniel")
    @patch("suite_user.get_external_user_id", return_value="daniel@example.com")
    def test_write_namespace_matches_cc_fetch_keys(
        self,
        _ext,
        _ws,
        fetch_keys,
        scoped,
    ) -> None:
        diag = build_activity_write_diagnostics(
            event_type="draft_analysis_created",
            resume_title="Continue Draft Analysis",
            resume_key="bb:draft_lab:ROOM-1",
            page="Draft Simulation Test Mode",
            metrics={
                "team_matchup": "Daniel vs Ariel",
                "teams": ["Daniel", "Ariel"],
                "draft_room_id": "ROOM-1",
            },
        )
        self.assertEqual(diag["cloud_app_key_baseball"], "baseball__daniel")
        self.assertEqual(sorted(diag["workspace_storage_app_keys"]), ["baseball__daniel"])
        self.assertEqual(diag["suite_external_id"], "daniel@example.com")
        self.assertEqual(diag["events_table"], "suite_activity_events")

    def test_stamp_metrics_includes_workspace(self) -> None:
        with patch("suite_user.get_external_user_id", return_value="acct-1"):
            with patch("suite_workspace.get_active_workspace_id", return_value="daniel"):
                stamped = stamp_activity_metrics({"team_matchup": "Daniel vs Ariel"})
        self.assertEqual(stamped["suite_external_id"], "acct-1")
        self.assertEqual(stamped["workspace_id"], "daniel")
        self.assertEqual(stamped["team_matchup"], "Daniel vs Ariel")

    def test_activity_app_aliases_include_baseball_variants(self) -> None:
        self.assertIn("baseball-stat-app", ACTIVITY_APP_ALIASES)
        self.assertEqual(ACTIVITY_APP_ALIASES["Baseball Analytics"], "baseball")


if __name__ == "__main__":
    unittest.main()
