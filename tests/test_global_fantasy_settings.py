"""Tests for canonical league format propagation."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from baseball_persistent_state import build_baseball_disk_state
from global_fantasy_settings_state import (
    CANONICAL_POINTS,
    CANONICAL_ROTO,
    LIVE_SCORING_POINTS,
    LIVE_SCORING_ROTO,
    mirror_canonical_to_all_aliases,
    normalize_league_format,
    on_alias_format_changed,
    on_live_draft_scoring_changed,
    write_canonical_global_fantasy_settings,
)


class TestNormalizeLeagueFormat(unittest.TestCase):
    def test_variants(self) -> None:
        self.assertEqual(normalize_league_format("Points"), CANONICAL_POINTS)
        self.assertEqual(normalize_league_format("Points League"), CANONICAL_POINTS)
        self.assertEqual(normalize_league_format("Roto (5x5)"), CANONICAL_ROTO)
        self.assertEqual(normalize_league_format("5x5 Roto"), CANONICAL_ROTO)


class TestFormatPropagation(unittest.TestCase):
    def test_write_canonical_mirrors_aliases_and_live_scoring(self) -> None:
        session: dict = {}
        write_canonical_global_fantasy_settings(session, format_="Points League", reason="test")
        self.assertEqual(session["room_format"], CANONICAL_POINTS)
        self.assertEqual(session["draft_lab_scoring_type"], CANONICAL_POINTS)
        self.assertEqual(session["fantasy_market_format"], CANONICAL_POINTS)
        self.assertEqual(session["live_draft_scoring"], LIVE_SCORING_POINTS)

    def test_on_alias_format_changed_from_draft_lab(self) -> None:
        session = {"draft_lab_scoring_type": "Points League"}
        on_alias_format_changed(session, "draft_lab_scoring_type")
        self.assertEqual(session["room_format"], CANONICAL_POINTS)
        self.assertEqual(session["draft_format"], CANONICAL_POINTS)
        self.assertEqual(session["live_draft_scoring"], LIVE_SCORING_POINTS)

    def test_live_draft_scoring_promotes_to_canonical(self) -> None:
        session = {"live_draft_scoring": LIVE_SCORING_ROTO}
        on_live_draft_scoring_changed(session)
        self.assertEqual(session["room_format"], CANONICAL_ROTO)
        self.assertEqual(session["draft_lab_scoring_type"], CANONICAL_ROTO)

    def test_mirror_after_restore(self) -> None:
        session = {
            "room_format": CANONICAL_POINTS,
            "draft_lab_scoring_type": CANONICAL_ROTO,
            "live_draft_scoring": LIVE_SCORING_ROTO,
        }
        mirror_canonical_to_all_aliases(session)
        self.assertEqual(session["draft_lab_scoring_type"], CANONICAL_POINTS)
        self.assertEqual(session["live_draft_scoring"], LIVE_SCORING_POINTS)


class TestTeamPropagation(unittest.TestCase):
    def test_write_canonical_team_mirrors_aliases(self) -> None:
        session: dict = {}
        write_canonical_global_fantasy_settings(session, team="Daniel", reason="test")
        self.assertEqual(session["room_your_team"], "Daniel")
        self.assertEqual(session["draft_assistant_synced_team"], "Daniel")
        self.assertEqual(session["sleeper_sync_team"], "Daniel")

    def test_active_team_from_draft_room_when_no_live_draft(self) -> None:
        from global_fantasy_settings_state import active_fantasy_team_source, get_active_fantasy_team

        session = {"room_your_team": "Daniel"}
        self.assertEqual(active_fantasy_team_source(session), "draft_room")
        self.assertEqual(get_active_fantasy_team(session), "Daniel")

    def test_active_draft_overrides_draft_room_team_and_label(self) -> None:
        from fantasy_league_context import FANTASY_LEAGUE_CONTEXT_STATE_KEY
        from global_fantasy_settings_state import (
            active_fantasy_team_label,
            active_fantasy_team_source,
            get_active_fantasy_team,
        )

        session = {
            "room_your_team": "Simulator Team",
            FANTASY_LEAGUE_CONTEXT_STATE_KEY: {
                "active_league_context_id": "ctx1",
                "contexts": {
                    "ctx1": {
                        "league_context_id": "ctx1",
                        "my_team_name": "Daniel",
                        "display_name": "Practice Draft",
                    }
                },
            },
        }
        self.assertEqual(active_fantasy_team_source(session), "active_draft")
        self.assertEqual(get_active_fantasy_team(session), "Daniel")
        self.assertEqual(active_fantasy_team_label(session), "Daniel (Practice Draft)")

    def test_active_team_from_live_draft_when_in_progress(self) -> None:
        from global_fantasy_settings_state import active_fantasy_team_source, get_active_fantasy_team

        session = {
            "room_your_team": "Daniel",
            "live_draft_room": {
                "status": "in_progress",
                "draft_room_id": "test",
                "config": {"user_team": "Team A"},
                "teams": ["Team A", "Team B"],
            },
        }
        self.assertEqual(active_fantasy_team_source(session), "live_draft")
        self.assertEqual(get_active_fantasy_team(session), "Team A")

    def test_multiplayer_uses_participant_team(self) -> None:
        from global_fantasy_settings_state import get_active_fantasy_team

        session = {
            "room_your_team": "Team 1",
            "active_shared_draft_room_code": "ABC123",
            "draft_room_participant_team": "Team 2",
            "live_draft_room": {
                "status": "in_progress",
                "config": {"user_team": "Team 1", "your_team": "Team 1"},
            },
        }
        self.assertEqual(get_active_fantasy_team(session), "Team 2")


class TestExtractPlayerFromQuestion(unittest.TestCase):
    def test_wagaman_team_fit_question(self) -> None:
        from applied_math_context import extract_player_from_question

        q = "Would Eric Wagaman help my team if I draft him?"
        self.assertEqual(extract_player_from_question(q), "Eric Wagaman")

    def test_wagaman_fantasy_team_sleeper_question(self) -> None:
        from applied_math_context import extract_player_from_question, is_named_player_team_fit_question

        q = "Would Eric Wagaman help my fantasy team as a sleeper?"
        self.assertEqual(extract_player_from_question(q), "Eric Wagaman")
        self.assertTrue(is_named_player_team_fit_question(q))


class TestLineupFormatSync(unittest.TestCase):
    def test_canonical_points_syncs_to_lineup_format(self) -> None:
        from global_fantasy_settings_state import sync_lineup_format_from_canonical, write_canonical_global_fantasy_settings

        session: dict = {"lineup_format": "5x5 Roto"}
        write_canonical_global_fantasy_settings(session, format_="Points League", reason="test")
        sync_lineup_format_from_canonical(session)
        self.assertEqual(session["lineup_format"], CANONICAL_POINTS)
        self.assertEqual(session["standings_scoring_format"], CANONICAL_POINTS)

    def test_lineup_h2h_preserved_when_canonical_changes(self) -> None:
        from global_fantasy_settings_state import sync_lineup_format_from_canonical, write_canonical_global_fantasy_settings

        session = {"lineup_format": "Head-to-Head Categories", "room_format": CANONICAL_ROTO}
        write_canonical_global_fantasy_settings(session, format_=CANONICAL_POINTS, reason="test")
        sync_lineup_format_from_canonical(session)
        self.assertEqual(session["lineup_format"], "Head-to-Head Categories")

    def test_lineup_format_excluded_from_page_snapshot(self) -> None:
        import page_state as pg
        from global_fantasy_settings_state import global_settings_snapshot_excluded_keys

        self.assertIn("lineup_format", global_settings_snapshot_excluded_keys())
        session = {
            "room_format": CANONICAL_POINTS,
            "lineup_format": CANONICAL_ROTO,
            "lineup_bench_rows": 12,
            "page_filter_state": {
                "Fantasy Lineup Assistant": {
                    "lineup_format": CANONICAL_ROTO,
                    "lineup_bench_rows": 8,
                }
            },
        }
        pg.restore_page_state(session, "Fantasy Lineup Assistant", session["page_filter_state"])
        self.assertEqual(session["lineup_bench_rows"], 8)
        # lineup_format not restored from snapshot — global sync applies on page load.

    def test_lineup_format_change_updates_canonical(self) -> None:
        from global_fantasy_settings_state import on_lineup_format_changed

        session = {"lineup_format": "Points League", "room_format": CANONICAL_ROTO}
        on_lineup_format_changed(session)
        self.assertEqual(session["room_format"], CANONICAL_POINTS)
        self.assertEqual(session["draft_format"], CANONICAL_POINTS)


class TestTeamPropagationPageRestore(unittest.TestCase):
    def test_page_restore_does_not_overwrite_canonical_team(self) -> None:
        import page_state as pg

        session = {
            "room_your_team": "Daniel",
            "draft_assistant_synced_team": "Daniel",
            "page_filter_state": {
                "Draft Assistant Simulator": {
                    "draft_assistant_synced_team": "Team 2",
                    "draft_window": 4,
                }
            },
        }
        pg.restore_page_state(session, "Draft Assistant Simulator", session["page_filter_state"])
        self.assertEqual(session["room_your_team"], "Daniel")
        self.assertEqual(session["draft_assistant_synced_team"], "Daniel")
        self.assertEqual(session["draft_window"], 4)


class TestNanCloudSave(unittest.TestCase):
    def test_build_disk_state_json_serializable_with_nan(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Draft Room Simulator",
            "page_filter_state": {},
            "room_format": CANONICAL_ROTO,
            "draft_lab_results": {
                "draft": [{"HR": float("nan"), "Player": "Test"}],
            },
        }
        blob = build_baseball_disk_state(st)
        json.dumps(blob)


if __name__ == "__main__":
    unittest.main()
