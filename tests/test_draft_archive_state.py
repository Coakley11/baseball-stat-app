"""Tests for saved draft team archive."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_archive_state import (
    DRAFT_ARCHIVE_KEY,
    DRAFT_TYPE_LIVE,
    activate_draft_archive,
    archive_roster_dataframe,
    build_roster_stats_from_archive,
    clear_active_draft_archive,
    delete_draft_archive,
    draft_type_display,
    duplicate_draft_archive,
    format_archive_modified,
    get_active_draft_archive,
    get_draft_archive,
    list_draft_archives,
    rename_draft_archive,
    save_live_draft_team_archive,
    save_simulator_team_archive,
    set_active_draft_archive,
)


def _normalize(name: str) -> str:
    return str(name or "").strip().lower()


class DraftArchiveTests(unittest.TestCase):
    def test_save_live_draft_team_persists_in_session(self) -> None:
        session: dict = {}
        room = {
            "config": {
                "league_name": "Test League",
                "slots": {"C": 1, "SS": 1, "OF": 1, "1B": 0, "2B": 0, "3B": 0, "DH": 0, "P": 0, "BN": 0},
                "fantasy_format": "5x5 Roto",
            },
            "rosters": {
                "Team A": [{"fullName": "Player One", "Primary Position": "SS", "Expected Fantasy Value": 0.8}],
            },
            "draft_board": [
                {"Fantasy Team": "Team A", "fullName": "Player One", "Pick": 1, "Round": 1},
            ],
        }
        entry = save_live_draft_team_archive(session, room, team_name="Team A", draft_name="My Live Draft")
        self.assertEqual(entry["draft_type"], DRAFT_TYPE_LIVE)
        self.assertEqual(len(session[DRAFT_ARCHIVE_KEY]), 1)
        self.assertEqual(list_draft_archives(session)[0]["draft_name"], "My Live Draft")

    def test_simulator_save_and_active_selection(self) -> None:
        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Team A", "Player": "Player X", "Pick": 1, "Round": 1, "Primary Position": "OF"},
            ]
        )
        entry = save_simulator_team_archive(session, board, team_name="Team A", draft_name="Mock 2026")
        set_active_draft_archive(session, entry["draft_id"])
        active = get_active_draft_archive(session)
        assert active is not None
        self.assertEqual(active["draft_id"], entry["draft_id"])
        df = archive_roster_dataframe(active)
        self.assertFalse(df.empty)
        self.assertIn("Player", df.columns)
        self.assertEqual(df.iloc[0]["Team"], "Team A")

    def test_multiple_archives_preserved_on_activate(self) -> None:
        session: dict = {}
        board = pd.DataFrame([{"Team": "A", "Player": "P1", "Pick": 1, "Round": 1}])
        first = save_simulator_team_archive(session, board, team_name="A", draft_name="Draft 1")
        second = save_simulator_team_archive(
            session,
            pd.DataFrame([{"Team": "B", "Player": "P2", "Pick": 1, "Round": 1}]),
            team_name="B",
            draft_name="Draft 2",
        )
        activate_draft_archive(session, second["draft_id"])
        self.assertEqual(len(list_draft_archives(session)), 2)
        active = get_active_draft_archive(session)
        assert active is not None
        self.assertEqual(active["draft_id"], second["draft_id"])
        self.assertEqual(get_draft_archive(session, first["draft_id"])["draft_name"], "Draft 1")

    def test_build_roster_stats_from_archive(self) -> None:
        session: dict = {}
        board = pd.DataFrame(
            [{"Team": "Team A", "Player": "Aaron Judge", "Pick": 1, "Round": 1, "Primary Position": "OF"}]
        )
        entry = save_simulator_team_archive(session, board, team_name="Team A")
        stats = pd.DataFrame([{"Player": "Aaron Judge", "HR": 20, "RBI": 50}])
        merged = build_roster_stats_from_archive(entry, stats, normalize_name_fn=_normalize)
        self.assertFalse(merged.empty)
        self.assertEqual(int(merged.iloc[0]["HR"]), 20)
        self.assertEqual(str(merged.iloc[0]["Team"]), "Team A")

    def test_clear_active_draft_archive(self) -> None:
        session: dict = {}
        board = pd.DataFrame([{"Team": "A", "Player": "P", "Pick": 1, "Round": 1}])
        entry = save_simulator_team_archive(session, board, team_name="A")
        activate_draft_archive(session, entry["draft_id"])
        clear_active_draft_archive(session)
        self.assertIsNone(get_active_draft_archive(session))
        self.assertEqual(len(list_draft_archives(session)), 1)

    def test_rename_duplicate_delete_archive(self) -> None:
        session: dict = {}
        board = pd.DataFrame([{"Team": "A", "Player": "P1", "Pick": 1, "Round": 1}])
        entry = save_simulator_team_archive(session, board, team_name="A", draft_name="Mock 2026")
        draft_id = str(entry["draft_id"])
        renamed = rename_draft_archive(session, draft_id, "Renamed Draft")
        assert renamed is not None
        self.assertEqual(renamed["draft_name"], "Renamed Draft")
        dup = duplicate_draft_archive(session, draft_id)
        assert dup is not None
        self.assertNotEqual(dup["draft_id"], draft_id)
        self.assertEqual(len(list_draft_archives(session)), 2)
        activate_draft_archive(session, draft_id)
        self.assertTrue(delete_draft_archive(session, draft_id))
        self.assertIsNone(get_active_draft_archive(session))
        self.assertEqual(len(list_draft_archives(session)), 1)
        self.assertIsNotNone(get_draft_archive(session, dup["draft_id"]))

    def test_draft_type_display_and_modified(self) -> None:
        entry = {
            "draft_type": DRAFT_TYPE_LIVE,
            "updated_at": "2026-07-03T12:00:00+00:00",
        }
        self.assertEqual(draft_type_display(entry), "Live Draft")
        self.assertIn("2026", format_archive_modified(entry))


if __name__ == "__main__":
    unittest.main()
