"""Command Center integration smoke tests — meaningful Baseball workflow activity."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from baseball_activity import (
    log_historical_analysis,
    log_player_comparison,
    log_saved_draft_team_loaded,
    log_saved_draft_team_saved,
    log_standings_updated,
)
from baseball_archive_activity import log_saved_draft_archived, log_saved_draft_activated
from baseball_draft_activity import log_live_draft_pick, log_live_draft_room_created
from suite_deep_links import build_resume_action_url
from suite_resume_launch import _apply_baseball
from historical_state import apply_pending_historical_resume


def _sample_room(*, picks: int = 0, player: str = "") -> dict:
    board = []
    for i in range(picks):
        row = {"pick": i + 1}
        if player and i == picks - 1:
            row["fullName"] = player
        board.append(row)
    return {
        "draft_room_id": "ROOM-CC01",
        "teams": ["Daniel", "Ariel"],
        "config": {"picks_per_team": 10, "teams": ["Daniel", "Ariel"]},
        "draft_board": board,
        "status": "in_progress",
        "current_pick_index": picks,
    }


def _archive_entry(**overrides) -> dict:
    base = {
        "draft_id": "DRAFT-001",
        "draft_name": "Mock Draft #2",
        "team_name": "Daniel",
        "draft_type": "simulator",
        "players": ["Aaron Judge", "Mike Trout"],
        "fantasy_format": "5x5 Roto",
        "updated_at": "2026-07-02T12:00:00+00:00",
    }
    base.update(overrides)
    return base


class TestBaseballCommandCenterActivity(unittest.TestCase):
    @patch("suite_activity_client.record_activity")
    def test_live_draft_pick_includes_player_name(self, record_mock) -> None:
        session: dict = {}
        log_live_draft_pick(_sample_room(picks=1, player="Aaron Judge"), session=session)
        record_mock.assert_called_once()
        kwargs = record_mock.call_args[1]
        self.assertEqual(kwargs["summary"], "Made draft pick: Aaron Judge")
        self.assertEqual(kwargs["metrics"]["player"], "Aaron Judge")
        self.assertEqual(kwargs["metrics"]["cc_card_kind"], "continue")
        self.assertEqual(kwargs["resume_key"], "bb:live_draft:ROOM-CC01")

    @patch("suite_activity_client.record_activity")
    def test_live_draft_created_summary(self, record_mock) -> None:
        log_live_draft_room_created(_sample_room(), session={})
        kwargs = record_mock.call_args[1]
        self.assertIn("Started Live Draft", kwargs["summary"])

    @patch("suite_activity_client.record_activity")
    def test_saved_draft_archived_continue_card(self, record_mock) -> None:
        session: dict = {}
        log_saved_draft_archived(_archive_entry(), session=session)
        record_mock.assert_called_once()
        _app, event, *_rest = record_mock.call_args[0]
        kwargs = record_mock.call_args[1]
        self.assertEqual(event, "saved_draft_archived")
        self.assertEqual(kwargs["summary"], "Saved draft team: Mock Draft #2")
        self.assertEqual(kwargs["resume_key"], "bb:saved_draft:DRAFT-001")
        self.assertEqual(kwargs["metrics"]["cc_card_kind"], "continue")
        self.assertEqual(kwargs["metrics"]["workstream"], "baseball_draft")

    @patch("suite_activity_client.record_activity")
    def test_saved_draft_activate_deduped(self, record_mock) -> None:
        session: dict = {}
        entry = _archive_entry()
        log_saved_draft_activated(entry, session=session, target_page="Fantasy Standings Tracker")
        log_saved_draft_activated(entry, session=session, target_page="Fantasy Standings Tracker")
        self.assertEqual(record_mock.call_count, 1)
        kwargs = record_mock.call_args[1]
        self.assertIn("Standings Tracker", kwargs["summary"])

    @patch("suite_activity_client.record_activity")
    def test_hof_style_comparison_activity(self, record_mock) -> None:
        log_player_comparison("Juan Soto", "Ken Griffey Jr.")
        kwargs = record_mock.call_args[1]
        self.assertEqual(kwargs["summary"], "Compared Juan Soto vs Ken Griffey Jr.")
        self.assertEqual(kwargs["resume_key"], "compare:Juan Soto:Ken Griffey Jr.")
        self.assertEqual(kwargs["metrics"]["cc_card_kind"], "continue")

    @patch("suite_activity_client.record_activity")
    def test_historical_analysis_continue_card(self, record_mock) -> None:
        log_historical_analysis(sort_stat="HR", year_start=2000, year_end=2024, row_count=500, top_player="Barry Bonds")
        _app, event, *_rest = record_mock.call_args[0]
        kwargs = record_mock.call_args[1]
        self.assertEqual(event, "historical_analysis")
        self.assertIn("Ran historical analysis", kwargs["summary"])
        self.assertEqual(kwargs["resume_key"], "historical:HR:2000-2024")
        self.assertEqual(kwargs["metrics"]["workstream"], "baseball_research")

    @patch("suite_activity_client.record_activity")
    def test_standings_updated_activity(self, record_mock) -> None:
        log_standings_updated(
            team="Daniel",
            season=2026,
            scoring_format="5x5 Roto",
            team_count=12,
            saved_draft_name="Mock Draft #2",
        )
        kwargs = record_mock.call_args[1]
        self.assertIn("Updated fantasy standings analysis", kwargs["summary"])
        self.assertTrue(kwargs["resume_key"].startswith("bb:standings:"))

    def test_saved_draft_deep_link(self) -> None:
        url = build_resume_action_url(
            "baseball",
            resume_key="bb:saved_draft:DRAFT-001",
            page="Saved Draft Library",
            metrics={"draft_id": "DRAFT-001", "draft_name": "Mock Draft #2"},
            base_url="https://example.test",
        )
        self.assertIn("suite_saved_draft=DRAFT-001", url)
        self.assertIn("suite_page=Saved+Draft+Library", url)

    def test_historical_deep_link(self) -> None:
        url = build_resume_action_url(
            "baseball",
            resume_key="historical:HR:2000-2024",
            page="Historical Explorer",
            metrics={"sort_stat": "HR", "year_start": "2000", "year_end": "2024"},
            base_url="https://example.test",
        )
        self.assertIn("suite_historical_stat=HR", url)
        self.assertIn("suite_historical_year_start=2000", url)
        self.assertIn("suite_historical_year_end=2024", url)

    @patch("draft_archive_state.activate_draft_archive", return_value=_archive_entry())
    def test_resume_launch_restores_saved_draft(self, activate_mock) -> None:
        class _QP:
            def __init__(self, mapping: dict[str, str]):
                self._mapping = mapping

            def get(self, key):
                return self._mapping.get(key, "")

        class _ST:
            def __init__(self):
                self.session_state: dict = {}
                self.query_params = _QP(
                    {
                        "suite_resume": "bb:saved_draft:DRAFT-001",
                        "suite_page": "Saved Draft Library",
                        "suite_saved_draft": "DRAFT-001",
                    }
                )

        st = _ST()
        _apply_baseball(st, "bb:saved_draft:DRAFT-001", "Saved Draft Library")
        activate_mock.assert_called_once()
        self.assertEqual(st.session_state.get("_navigate_to_page"), "Saved Draft Library")

    def test_resume_launch_restores_historical_filters(self) -> None:
        class _QP:
            def __init__(self, mapping: dict[str, str]):
                self._mapping = mapping

            def get(self, key):
                return self._mapping.get(key, "")

        class _ST:
            def __init__(self):
                self.session_state: dict = {}
                self.query_params = _QP(
                    {
                        "suite_historical_stat": "HR",
                        "suite_historical_year_start": "2000",
                        "suite_historical_year_end": "2024",
                    }
                )

        st = _ST()
        _apply_baseball(st, "historical:HR:2000-2024", "Historical Explorer")
        self.assertEqual(st.session_state.get("_pending_historical_stat"), "HR")
        self.assertEqual(st.session_state.get("_pending_historical_year_start"), "2000")
        self.assertEqual(st.session_state.get("_pending_historical_year_end"), "2024")

    def test_apply_pending_historical_resume_writes_filters(self) -> None:
        session = {
            "_pending_historical_stat": "HR",
            "_pending_historical_year_start": "1998",
            "_pending_historical_year_end": "2008",
        }
        self.assertTrue(apply_pending_historical_resume(session))
        meta = session.get("historical_state") or {}
        filters = meta.get("filters") or {}
        self.assertEqual(filters.get("historical_sort_stat_filter"), "HR")
        self.assertEqual(filters.get("historical_year_range_filter"), (1998, 2008))

    @patch("suite_activity_client.record_activity")
    def test_direct_saved_draft_helpers(self, record_mock) -> None:
        log_saved_draft_team_saved(
            draft_id="X1",
            draft_name="Practice Draft",
            team_name="Team A",
            draft_type="live_draft",
            player_count=15,
        )
        log_saved_draft_team_loaded(
            draft_id="X1",
            draft_name="Practice Draft",
            team_name="Team A",
            target_page="Fantasy Standings Tracker",
        )
        self.assertEqual(record_mock.call_count, 2)
        loaded_summary = record_mock.call_args_list[1][1]["summary"]
        self.assertIn("Loaded saved team", loaded_summary)


if __name__ == "__main__":
    unittest.main()
