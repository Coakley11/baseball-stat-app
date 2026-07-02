"""Regression tests for shared draft player profile cards and projection stat lines."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from player_photos import (
    assign_roster_recap_slots,
    compact_fantasy_stat_line,
    extract_projection_value,
    get_player_photo_info,
    is_current_draft_pool_player,
    lookup_row_by_player_name,
    render_completed_roster_recap,
    render_comparison_profile_cards,
    render_queue_headshot_html,
)


class DraftProfileCardStatTests(unittest.TestCase):
    def test_uses_projection_not_career_hr(self) -> None:
        row = pd.Series({"HR": 148, "proj_HR": 48, "proj_RBI": 111, "proj_R": 105, "proj_SB": 9, "proj_BA": 0.289})
        line = compact_fantasy_stat_line(row)
        self.assertIn("Proj:", line)
        self.assertIn("48 HR", line)
        self.assertNotIn("148", line)

    def test_judge_ohtani_impossible_hr_suppressed(self) -> None:
        judge = pd.Series({"fullName": "Aaron Judge", "HR": 148, "proj_HR": 148})
        ohtani = pd.Series({"fullName": "Shohei Ohtani", "HR": 153, "proj_HR": 153})
        self.assertEqual(compact_fantasy_stat_line(judge), "")
        self.assertEqual(compact_fantasy_stat_line(ohtani), "")

    def test_plausible_projection_line_includes_proj_label(self) -> None:
        row = pd.Series({"proj_HR": 48, "proj_RBI": 111, "proj_R": 105, "proj_SB": 9, "proj_BA": 0.289})
        line = compact_fantasy_stat_line(row)
        self.assertTrue(line.startswith("Proj:"))
        self.assertIn("0.289 AVG", line)

    def test_extract_projection_ignores_raw_counting_stats(self) -> None:
        row = pd.Series({"HR": 99, "proj_HR": 42})
        self.assertEqual(extract_projection_value(row, "HR"), 42.0)


class DraftQueuePhotoTests(unittest.TestCase):
    def test_queue_headshot_html_with_photo(self) -> None:
        info = get_player_photo_info(full_name="Aaron Judge", use_api=False)
        html = render_queue_headshot_html(info)
        self.assertIn("bb-queue-headshot", html)
        self.assertTrue("img" in html or "placeholder" in html)

    def test_queue_headshot_placeholder_without_mlbam(self) -> None:
        html = render_queue_headshot_html({"headshot_url": None, "full_name": "Unknown Player"})
        self.assertIn("bb-queue-placeholder", html)
        self.assertIn("⚾", html)


class CompletedRosterRecapTests(unittest.TestCase):
    def test_assign_roster_recap_slots_by_position(self) -> None:
        roster = pd.DataFrame(
            [
                {"fullName": "Cal Raleigh", "Primary Position": "C", "Expected Fantasy Value": 0.9, "proj_HR": 30},
                {"fullName": "Freddie Freeman", "Primary Position": "1B", "Expected Fantasy Value": 0.85, "proj_HR": 28},
                {"fullName": "Aaron Judge", "Primary Position": "OF", "Expected Fantasy Value": 0.95, "proj_HR": 48},
            ]
        )
        slots = assign_roster_recap_slots(roster)
        labels = [s for s, _ in slots]
        names = [str(r["fullName"]) for _, r in slots]
        self.assertIn("C", labels)
        self.assertIn("1B", labels)
        self.assertTrue(any(l.startswith("OF") for l in labels))
        self.assertIn("Cal Raleigh", names)
        self.assertIn("Aaron Judge", names)

    @patch("player_photos.get_player_photo_info")
    @patch("player_photos._safe_markdown")
    def test_completed_recap_renders_photos(self, mock_md: MagicMock, mock_photo: MagicMock) -> None:
        mock_photo.return_value = {"headshot_url": "https://example.com/a.jpg", "full_name": "Aaron Judge"}
        roster = pd.DataFrame(
            [{"fullName": "Aaron Judge", "Primary Position": "OF", "Expected Fantasy Value": 0.9, "proj_HR": 48, "proj_BA": 0.289}]
        )
        st = MagicMock()
        render_completed_roster_recap(st, roster, team_name="Daniel")
        self.assertTrue(mock_md.called)
        html = str(mock_md.call_args[0][1])
        self.assertIn("bb-roster-recap-grid", html)
        self.assertIn("Aaron Judge", html)


class SleepersAndComparisonCardTests(unittest.TestCase):
    def test_sleepers_row_renders_profile_card(self) -> None:
        from player_photos import build_draft_profile_card_html

        row = pd.Series(
            {
                "fullName": "Tyler O'Neill",
                "Primary Position": "OF",
                "Team": "BAL",
                "proj_HR": 32,
                "proj_RBI": 78,
                "Expected Fantasy Value": 0.72,
                "Reason": "Positive fantasy edge vs market.",
            }
        )
        info = get_player_photo_info(full_name="Tyler O'Neill", use_api=False)
        html = build_draft_profile_card_html(row, info, reason=str(row["Reason"]), show_adp=True)
        self.assertIn("Tyler O'Neill", html)
        self.assertIn("Proj:", html)
        self.assertIn("Positive fantasy edge", html)

    @patch("player_photos._safe_markdown")
    def test_comparison_historical_player_no_projections(self, mock_md: MagicMock) -> None:
        yearly = pd.DataFrame(
            [
                {"playerID": "ruthba01", "yearID": 1927, "fullName": "Babe Ruth"},
                {"playerID": "judgeaa01", "yearID": 2025, "fullName": "Aaron Judge"},
            ]
        )
        st = MagicMock()
        render_comparison_profile_cards(
            st,
            labels=["Babe Ruth (1927)"],
            player_ids=["ruthba01"],
            yearly_df=yearly,
            projection_lookup_df=pd.DataFrame(),
        )
        html = str(mock_md.call_args[0][1])
        self.assertIn("Not applicable — historical player", html)
        self.assertNotIn("Proj:", html)

    @patch("player_photos._safe_markdown")
    def test_comparison_active_player_shows_projections(self, mock_md: MagicMock) -> None:
        yearly = pd.DataFrame(
            [
                {"playerID": "judgeaa01", "yearID": 2025, "fullName": "Aaron Judge"},
                {"playerID": "cobbty01", "yearID": 1928, "fullName": "Ty Cobb"},
            ]
        )
        proj = pd.DataFrame(
            [{"fullName": "Aaron Judge", "proj_HR": 48, "proj_RBI": 111, "proj_R": 105, "proj_SB": 9, "proj_BA": 0.289}]
        )
        st = MagicMock()
        render_comparison_profile_cards(
            st,
            labels=["Aaron Judge"],
            player_ids=["judgeaa01"],
            yearly_df=yearly,
            projection_lookup_df=proj,
        )
        html = str(mock_md.call_args[0][1])
        self.assertIn("Proj:", html)
        self.assertNotIn("Not applicable — historical player", html)

    def test_lookup_row_by_player_name(self) -> None:
        pool = pd.DataFrame([{"fullName": "Aaron Judge", "proj_HR": 48}])
        row = lookup_row_by_player_name("Aaron Judge", pool)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(int(row["proj_HR"]), 48)

    def test_is_current_draft_pool_player_recent(self) -> None:
        yearly = pd.DataFrame(
            [
                {"playerID": "judgeaa01", "yearID": 2025},
                {"playerID": "cobbty01", "yearID": 1928},
            ]
        )
        self.assertTrue(is_current_draft_pool_player("judgeaa01", yearly))
        self.assertFalse(is_current_draft_pool_player("cobbty01", yearly))


if __name__ == "__main__":
    unittest.main()
