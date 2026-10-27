"""Regression tests for uploaded/shared league save classification."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_archive_state import DRAFT_ARCHIVE_KEY, DRAFT_TYPE_IMPORTED, DRAFT_TYPE_SIMULATOR, list_draft_archives
from draft_import_pipeline import board_should_save_as_imported_league
from fantasy_league_context import (
    CONTEXT_TYPE_REAL_LEAGUE,
    SOURCE_IMPORTED_DRAFT,
    get_league_context_for_archive,
    is_ephemeral_league_context_id,
    repair_misclassified_imported_league_archives,
    resolve_canonical_save_ids,
    upsert_league_context,
)
from tests.test_imported_shared_league import _sample_board


class ImportedLeagueSavePathTests(unittest.TestCase):
    def test_board_should_save_as_imported_when_validated_import_meta(self) -> None:
        session = {
            "canonical_draft_meta": {"source": "validated_import", "pick_count": 4},
        }
        self.assertTrue(board_should_save_as_imported_league(session, _sample_board()))

    def test_resolve_canonical_save_ids_ignores_ephemeral_context(self) -> None:
        session: dict = {"fantasy_league_context_state": {"schema_version": 1, "contexts": {}, "active_league_context_id": ""}}
        board = _sample_board()
        from fantasy_league_context import build_league_rosters_from_simulator_board

        rosters = build_league_rosters_from_simulator_board(board, "Daniel")
        fp = resolve_canonical_save_ids(session, league_rosters=rosters)[2]
        ephemeral = {
            "league_context_id": "__ephemeral_simulator__",
            "context_type": "mock_draft_simulation",
            "league_rosters": rosters,
            "metadata": {"draft_fingerprint": fp, "source": "draft_simulator"},
        }
        upsert_league_context(session, ephemeral)
        draft_id, league_context_id, _ = resolve_canonical_save_ids(
            session,
            league_rosters=rosters,
            draft_id="upload-fix-001",
        )
        self.assertFalse(is_ephemeral_league_context_id(str(league_context_id or "")))
        self.assertNotEqual(str(league_context_id or ""), "__ephemeral_simulator__")
        self.assertEqual(str(draft_id or ""), "upload-fix-001")

    def test_repair_misclassified_simulator_ephemeral_archive(self) -> None:
        session: dict = {
            "draft_archive_teams": [
                {
                    "draft_id": "upload001",
                    "draft_type": DRAFT_TYPE_SIMULATOR,
                    "draft_name": "Office League 2026",
                    "team_name": "Daniel",
                    "league_context_id": "__ephemeral_simulator__",
                    "league_rosters": {
                        "Daniel": {"team_name": "Daniel", "players": [{"player_name": "Aaron Judge"}]},
                        "Team 2": {"team_name": "Team 2", "players": [{"player_name": "Francisco Lindor"}]},
                        "Team 3": {"team_name": "Team 3", "players": [{"player_name": "Juan Soto"}]},
                        "Team 4": {"team_name": "Team 4", "players": [{"player_name": "Juan Yepez"}]},
                    },
                    "snapshot": {"team_count": 4, "my_team_player_count": 1},
                }
            ],
            "fantasy_league_context_state": {
                "schema_version": 1,
                "contexts": {
                    "__ephemeral_simulator__": {
                        "league_context_id": "__ephemeral_simulator__",
                        "context_type": "mock_draft_simulation",
                        "my_team_name": "Daniel",
                        "metadata": {"source": "draft_simulator"},
                        "league_rosters": {
                            "Daniel": {"team_name": "Daniel", "players": []},
                            "Team 2": {"team_name": "Team 2", "players": []},
                            "Team 3": {"team_name": "Team 3", "players": []},
                            "Team 4": {"team_name": "Team 4", "players": []},
                        },
                    }
                },
                "active_league_context_id": "",
            },
        }
        repaired = repair_misclassified_imported_league_archives(session)
        self.assertEqual(repaired, 1)
        entry = list_draft_archives(session)[0]
        self.assertEqual(entry.get("draft_type"), DRAFT_TYPE_IMPORTED)
        self.assertFalse(is_ephemeral_league_context_id(str(entry.get("league_context_id") or "")))
        context = get_league_context_for_archive(session, entry)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(str(context.get("context_type") or ""), CONTEXT_TYPE_REAL_LEAGUE)
        self.assertEqual(str((context.get("metadata") or {}).get("source") or ""), SOURCE_IMPORTED_DRAFT)


class MockDraftStaysMockAfterRepairTests(unittest.TestCase):
    """Hosted 2026-10-26: a saved multi-team mock draft must not turn into an Imported League.

    repair_misclassified_imported_league_archives used to convert every simulator archive with
    two or more teams (mock_draft_simulation from the simulator) into a real_league with an owner.
    """

    def test_four_team_simulator_save_survives_library_repairs(self) -> None:
        from fantasy_league_context import (
            CONTEXT_TYPE_MOCK_DRAFT_SIMULATION,
            get_league_context,
            save_simulator_league_context,
        )
        from library_repair_scheduler import run_gated_library_repairs

        session: dict = {}
        board = pd.DataFrame(
            [{"Team": f"Team {t}", "Player": f"Player {t}{r}", "Pick": i + 1}
             for i, (r, t) in enumerate((r, t) for r in range(2) for t in "ABCD")]
        )
        save_simulator_league_context(session, board, my_team_name="Team A", draft_name="Mock",
                                      defer_activation=True, save_only=True)
        run_gated_library_repairs(session)
        archive = list_draft_archives(session)[0]
        context = get_league_context(session, archive["league_context_id"]) or {}
        self.assertEqual(archive["draft_type"], DRAFT_TYPE_SIMULATOR)
        self.assertEqual(context.get("context_type"), CONTEXT_TYPE_MOCK_DRAFT_SIMULATION)
        self.assertFalse(context.get("team_ownership"))

    def test_mock_draft_is_not_repaired_while_an_import_board_is_loaded(self) -> None:
        from fantasy_league_context import save_simulator_league_context

        session: dict = {}
        board = pd.DataFrame([{"Team": "Team A", "Player": "P1", "Pick": 1}, {"Team": "Team B", "Player": "P2", "Pick": 2}])
        save_simulator_league_context(session, board, my_team_name="Team A", defer_activation=True, save_only=True)
        session["canonical_draft_meta"] = {"source": "validated_import", "pick_count": 2}
        self.assertEqual(repair_misclassified_imported_league_archives(session), 0)
        self.assertEqual(list_draft_archives(session)[0]["draft_type"], DRAFT_TYPE_SIMULATOR)


if __name__ == "__main__":
    unittest.main()
