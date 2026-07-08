"""Tests for imported shared league creation (UDSL-2/3)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from draft_archive_state import DRAFT_TYPE_IMPORTED, get_active_draft_archive, list_draft_archives
from draft_import_validation import import_review_ready_for_league, validate_imported_draft_df
from fantasy_league_context import (
    CONTEXT_TYPE_REAL_LEAGUE,
    get_active_league_context,
    get_league_context,
    save_imported_league_context,
)
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_league_team_ownership import get_team_ownership, owned_team_for_user
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store


def _sample_board() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Round": [1, 1, 1, 1],
            "Pick": [1, 2, 3, 4],
            "Team": ["Daniel", "Team 2", "Team 3", "Team 4"],
            "Player": ["Aaron Judge", "Francisco Lindor", "Juan Soto", "Juan Yepez"],
        }
    )


class TestImportedSharedLeague(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmpdir.name)))
        self.pool = pd.DataFrame(
            {
                "fullName": [
                    "Aaron Judge",
                    "Francisco Lindor",
                    "Juan Soto",
                    "Juan Yepez",
                ]
            }
        )
        self.session: dict = {"draft_shared_settings": {"fantasy_format": "5x5 Roto"}}

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmpdir.cleanup()

    def test_save_imported_league_context_creates_real_league(self) -> None:
        board = _sample_board()
        entry, context = save_imported_league_context(
            self.session,
            board,
            my_team_name="Daniel",
            draft_name="Office League 2026",
            league_name="Office League 2026",
            assign_team=False,
        )
        self.assertEqual(entry.get("draft_type"), DRAFT_TYPE_IMPORTED)
        self.assertEqual(context.get("context_type"), CONTEXT_TYPE_REAL_LEAGUE)
        self.assertEqual(context.get("my_team_name"), "Daniel")
        self.assertTrue(resolve_canonical_league_id(context))
        self.assertEqual(get_active_draft_archive(self.session), entry)
        active_ctx = get_active_league_context(self.session, respect_source_priority=False)
        self.assertEqual(active_ctx.get("league_context_id"), context.get("league_context_id"))

    def test_identical_import_reuses_fingerprint_ids(self) -> None:
        board = _sample_board()
        entry_a, ctx_a = save_imported_league_context(
            self.session,
            board,
            my_team_name="Daniel",
            draft_name="Office League",
            assign_team=False,
        )
        entry_b, ctx_b = save_imported_league_context(
            self.session,
            board,
            my_team_name="Team 2",
            draft_name="Office League copy",
            assign_team=False,
        )
        self.assertEqual(entry_a.get("draft_id"), entry_b.get("draft_id"))
        self.assertEqual(
            resolve_canonical_league_id(ctx_a),
            resolve_canonical_league_id(ctx_b),
        )
        self.assertEqual(len(list_draft_archives(self.session)), 1)

    def test_assign_team_on_save_records_ownership(self) -> None:
        board = _sample_board()
        _entry, context = save_imported_league_context(
            self.session,
            board,
            my_team_name="Daniel",
            draft_name="Claim Test League",
            assign_team=True,
        )
        league_context_id = str(context.get("league_context_id") or "")
        refreshed = get_league_context(self.session, league_context_id)
        self.assertIsNotNone(refreshed)
        ownership = get_team_ownership(refreshed)
        self.assertIn("Daniel", ownership)
        self.assertTrue(str(ownership["Daniel"].get("user_id") or "").strip())
        self.assertEqual(owned_team_for_user(refreshed), "Daniel")

    def test_league_gate_blocks_unresolved_before_save(self) -> None:
        import_df = pd.DataFrame(
            {
                "Round": [1, 1],
                "Pick": [1, 2],
                "Team": ["Daniel", "Team 2"],
                "Player": ["Aaron Judge", "Francsco Lindor"],
            }
        )
        review = validate_imported_draft_df(import_df, self.pool)
        self.assertFalse(import_review_ready_for_league(review, self.pool))
        review["rows"][1]["resolved_canonical"] = "Francisco Lindor"
        self.assertTrue(import_review_ready_for_league(review, self.pool))


if __name__ == "__main__":
    unittest.main()
