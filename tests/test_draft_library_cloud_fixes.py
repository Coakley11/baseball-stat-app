"""Regression tests for cloud merge, Draft Library save bridge, nav, and grades table."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from draft_archive_state import DRAFT_ARCHIVE_KEY, list_draft_archives
from draft_archive_ui import (
    SAVED_DRAFT_LIBRARY_PAGE,
    _persist_archive,
    schedule_page_navigation,
    schedule_saved_draft_library_navigation,
)
from draft_room_state import sync_draft_library_from_simulator_board
from fantasy_league_context import (
    FANTASY_LEAGUE_CONTEXT_STATE_KEY,
    list_league_contexts,
    save_simulator_league_context,
)
from suite_storage_supabase import _merge_full_session_preserve_richer_draft
from workflow_persist_guard import workflow_counts_from_session


def _mock_board(picks: int = 20) -> pd.DataFrame:
    rows = []
    teams = ["Team A", "Team B", "Team C", "Team D"]
    for i in range(picks):
        rows.append(
            {
                "Round": (i // len(teams)) + 1,
                "Pick": i + 1,
                "Team": teams[i % len(teams)],
                "Player": f"Player {i + 1}",
                "Expected Fantasy Value": 0.5 + (i * 0.01),
                "Draft Fit Score": 1.0,
                "Fantasy Edge": 0.1,
            }
        )
    return pd.DataFrame(rows)


class CloudMergeFilledPicksTests(unittest.TestCase):
    def test_empty_row_slots_do_not_clobber_filled_picks(self) -> None:
        empty_slots = {
            "draft_room_state": {
                "table_records": [
                    {"Round": 1, "Pick": i + 1, "Team": "Team A", "Player": ""}
                    for i in range(30)
                ],
                "pick_count": 0,
            },
            "draft_room_table": {
                "table_records": [
                    {"Round": 1, "Pick": i + 1, "Team": "Team A", "Player": ""}
                    for i in range(30)
                ],
                "pick_count": 0,
            },
        }
        incoming = {
            "active_page": "Draft Room Simulator",
            "draft_room_state": {
                "table_records": [
                    {"Round": 1, "Pick": i + 1, "Team": "Team A", "Player": f"Player {i + 1}"}
                    for i in range(20)
                ],
                "pick_count": 20,
            },
            "draft_room_table": {
                "table_records": [
                    {"Round": 1, "Pick": i + 1, "Team": "Team A", "Player": f"Player {i + 1}"}
                    for i in range(20)
                ],
                "pick_count": 20,
            },
        }
        merged = _merge_full_session_preserve_richer_draft(empty_slots, incoming)
        self.assertEqual(merged["draft_room_state"]["pick_count"], 20)
        self.assertEqual(merged["draft_room_state"]["table_records"][0]["Player"], "Player 1")


class DraftLibrarySaveBridgeTests(unittest.TestCase):
    def test_save_mock_draft_creates_library_entries(self) -> None:
        session: dict = {"room_your_team": "Daniel", "draft_shared_settings": {}}
        board = _mock_board(20)
        entry, context = save_simulator_league_context(
            session,
            board,
            my_team_name="Daniel",
            draft_name="Mock 4x5",
            defer_activation=True,
        )
        counts = workflow_counts_from_session(session)
        self.assertEqual(counts["saved_drafts"], 1)
        self.assertEqual(counts["league_contexts"], 1)
        self.assertEqual(len(list_draft_archives(session)), 1)
        self.assertEqual(len(list_league_contexts(session)), 1)
        self.assertTrue(str(entry.get("draft_id") or ""))
        self.assertTrue(str(context.get("league_context_id") or ""))

    @patch("baseball_persistent_state.force_save_baseball_state", return_value=True)
    def test_sync_draft_library_from_board_save(self, _mock_force_save: MagicMock) -> None:
        session: dict = {"room_your_team": "Daniel", "draft_shared_settings": {}}
        board = _mock_board(20)
        st = MagicMock()
        trace = sync_draft_library_from_simulator_board(st, session, board)
        self.assertTrue(trace.get("library_sync"))
        self.assertEqual(int(trace.get("saved_drafts") or 0), 1)
        self.assertEqual(int(trace.get("league_contexts") or 0), 1)

    def test_refresh_restores_library_counts_from_disk(self) -> None:
        session: dict = {"room_your_team": "Daniel", "draft_shared_settings": {}}
        board = _mock_board(20)
        save_simulator_league_context(session, board, my_team_name="Daniel", defer_activation=True)
        blob = {
            DRAFT_ARCHIVE_KEY: session[DRAFT_ARCHIVE_KEY],
            FANTASY_LEAGUE_CONTEXT_STATE_KEY: session[FANTASY_LEAGUE_CONTEXT_STATE_KEY],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseball_user_state.json"
            path.write_text(json.dumps(blob), encoding="utf-8")
            restored: dict = {}
            restored[DRAFT_ARCHIVE_KEY] = json.loads(path.read_text(encoding="utf-8"))[DRAFT_ARCHIVE_KEY]
            restored[FANTASY_LEAGUE_CONTEXT_STATE_KEY] = json.loads(path.read_text(encoding="utf-8"))[
                FANTASY_LEAGUE_CONTEXT_STATE_KEY
            ]
            counts = workflow_counts_from_session(restored)
            self.assertEqual(counts["saved_drafts"], 1)
            self.assertEqual(counts["league_contexts"], 1)

    @patch("baseball_persistent_state.force_save_baseball_state", return_value=False)
    def test_persist_archive_reports_failure_when_force_save_fails(self, _mock_force_save: MagicMock) -> None:
        session: dict = {"room_your_team": "Daniel", "draft_shared_settings": {}}
        board = _mock_board(8)
        entry, _ = save_simulator_league_context(session, board, my_team_name="Daniel", defer_activation=True)
        st = MagicMock()
        st.session_state = session

        ok = _persist_archive(session, st, reason="simulator_league_context_saved", entry=entry)

        self.assertFalse(ok)
        self.assertFalse(session["_draft_library_save_diag"]["persist_ok"])
        self.assertEqual(session["_draft_library_save_diag"]["draft_archive_count_after"], 1)


class ManageSavedDraftsNavigationTests(unittest.TestCase):
    def test_schedule_page_navigation_sets_navigation_intent_only(self) -> None:
        session = {"active_page": "Fantasy Standings Tracker", "main_sidebar_page": "Fantasy Standings Tracker"}
        schedule_page_navigation(session, SAVED_DRAFT_LIBRARY_PAGE)
        self.assertEqual(session["active_page"], "Fantasy Standings Tracker")
        self.assertEqual(session["main_sidebar_page"], "Fantasy Standings Tracker")
        self.assertEqual(session["_navigate_to_page"], SAVED_DRAFT_LIBRARY_PAGE)
        self.assertEqual(session["_skip_page_restore_for"], SAVED_DRAFT_LIBRARY_PAGE)
        self.assertTrue(session.get("_suite_page_user_nav"))

    def test_manage_saved_drafts_path_has_archives_available(self) -> None:
        session: dict = {"active_page": "Fantasy Standings Tracker"}
        board = _mock_board(5)
        save_simulator_league_context(session, board, my_team_name="Daniel", defer_activation=True)
        schedule_saved_draft_library_navigation(session, return_page="Fantasy Standings Tracker")
        self.assertEqual(session["_navigate_to_page"], SAVED_DRAFT_LIBRARY_PAGE)
        self.assertEqual(len(list_draft_archives(session)), 1)


class DemoRestorePriorityTests(unittest.TestCase):
    def test_disk_wins_when_more_drafts_than_cloud(self) -> None:
        from suite_cloud_state import pick_restore_session

        cloud = {
            "draft_archive_teams": [{"draft_id": "c1", "draft_name": "Cloud"}],
            "fantasy_league_context_state": {"contexts": {"lc1": {"league_context_id": "lc1"}}},
        }
        disk = {
            "draft_archive_teams": [
                {"draft_id": "d1", "draft_name": "Disk A"},
                {"draft_id": "d2", "draft_name": "Disk B"},
            ],
            "fantasy_league_context_state": {
                "contexts": {
                    "lc1": {"league_context_id": "lc1"},
                    "lc2": {"league_context_id": "lc2"},
                }
            },
        }
        picked = pick_restore_session(
            cloud,
            "2026-07-05T12:00:00",
            disk,
            "2026-07-05T11:00:00",
            cloud_first=True,
        )
        self.assertEqual(picked.source, "disk")
        self.assertTrue(
            "more saved drafts" in picked.reason or "richer saved drafts" in picked.reason,
            picked.reason,
        )

    def test_demo_disk_first_when_cloud_first_disabled(self) -> None:
        from suite_cloud_state import pick_restore_session

        cloud = {
            "draft_archive_teams": [{"draft_id": "c1", "draft_name": "Cloud"}],
            "active_page": "Saved Draft Library",
        }
        disk = {
            "draft_archive_teams": [{"draft_id": "d1", "draft_name": "Disk"}],
            "active_page": "Draft Room Simulator",
        }
        picked = pick_restore_session(
            cloud,
            "2026-07-05T13:00:00",
            disk,
            "2026-07-05T12:00:00",
            cloud_first=False,
        )
        self.assertEqual(picked.source, "disk")
        self.assertIn("disk-first", picked.reason.lower())


class PostDraftGradesTableTests(unittest.TestCase):
    def test_post_draft_grades_hide_total_player_grade(self) -> None:
        from draft_score_display import prepare_draft_scores_for_display

        df = pd.DataFrame(
            [
                {
                    "Fantasy Team": "Team A",
                    "Players Drafted": 5,
                    "Total Expected Fantasy Value": 2.5,
                    "Average Expected Fantasy Value": 0.5,
                    "Average Draft Fit Score": 1.05,
                    "Average Fantasy Edge": 0.12,
                    "Overall Draft Grade Score": 0.72,
                    "Draft Room Rank": 1,
                }
            ]
        )
        out = prepare_draft_scores_for_display(df)
        out = out.drop(columns=["Total Player Grade"], errors="ignore")
        self.assertNotIn("Total Player Grade", out.columns)
        self.assertIn("Average Player Grade", out.columns)
        self.assertIn("Average Roster Fit Score", out.columns)
        self.assertIn("Relative Draft Grade", out.columns)
        self.assertIn("Draft Rank", out.columns)
        self.assertAlmostEqual(float(out.loc[0, "Average Roster Fit Score"]), 1.05, places=2)


if __name__ == "__main__":
    unittest.main()
