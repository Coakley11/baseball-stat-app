"""Tests for one-shot admin draft archive repair."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fantasy_admin_draft_archive_repair import (
    bootstrap_session_for_workspace,
    build_context_from_shared_for_workspace,
    merge_repaired_workflow_into_blob,
    repair_workspace_session_for_league,
    run_league_draft_archive_repair,
)
from fantasy_league_context import FANTASY_LEAGUE_CONTEXT_STATE_KEY
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store


def _shared_doc(league_id: str = "league:test123", draft_id: str = "draft99") -> dict:
    return {
        "schema_version": 1,
        "league_id": league_id,
        "draft_id": draft_id,
        "draft_fingerprint": "fp99",
        "league_name": "2026 Main League",
        "revision": 3,
        "updated_at": "2026-07-09T00:00:00+00:00",
        "league_rosters": {
            "Daniel": {
                "team_name": "Daniel",
                "players": [{"player_name": "Aaron Judge", "player_key": "aaron judge"}],
            },
            "Team 2": {
                "team_name": "Team 2",
                "players": [{"player_name": "Mookie Betts", "player_key": "mookie betts"}],
            },
        },
        "team_ownership": {
            "Daniel": {"user_id": "user:donny", "display_name": "Daniel Cohen11"},
            "Team 2": {"user_id": "user:seal11", "display_name": "Coakley11"},
        },
        "trade_proposals": [
            {
                "trade_id": "trade-1",
                "status": "pending",
                "proposer_team": "Daniel",
                "recipient_team": "Team 2",
                "updated_at": "2026-07-09T01:00:00+00:00",
            }
        ],
        "league_invites": [],
        "league_activity": [],
    }


def _context_store(draft_id: str = "draft99", *, my_team: str = "Daniel", user_id: str = "user:donny") -> dict:
    return {
        FANTASY_LEAGUE_CONTEXT_STATE_KEY: {
            "active_league_context_id": f"archive:{draft_id}",
            "contexts": {
                f"archive:{draft_id}": {
                    "league_context_id": f"archive:{draft_id}",
                    "display_name": "2026 Main League",
                    "my_team_name": my_team,
                    "context_type": "real_league",
                    "source": "imported_draft",
                    "league_rosters": _shared_doc()["league_rosters"],
                    "team_ownership": {
                        my_team: {"user_id": user_id, "display_name": my_team},
                    },
                    "workflow": {"trade_proposals": _shared_doc()["trade_proposals"]},
                    "metadata": {
                        "source_draft_id": draft_id,
                        "league_id": "league:test123",
                        "draft_fingerprint": "fp99",
                    },
                }
            },
        }
    }


class AdminDraftArchiveRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        store_root = Path(self._tmp.name) / "shared"
        store_root.mkdir(parents=True)
        self.store = LocalFileSharedLeagueStore(root=store_root)
        set_shared_league_store(self.store)
        self.store.save(_shared_doc())

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmp.cleanup()

    def test_repair_rebuilds_archives_from_context_and_preserves_trades(self) -> None:
        from draft_archive_state import DRAFT_ARCHIVE_KEY, list_draft_archives

        session = bootstrap_session_for_workspace(
            "daniel",
            cloud_blob={**_context_store(), DRAFT_ARCHIVE_KEY: []},
        )
        session["_suite_auth_user_id"] = "user:donny"
        trace = repair_workspace_session_for_league(
            session,
            league_id="league:test123",
            shared_doc=_shared_doc(),
        )
        self.assertEqual(trace["before"]["raw_archive_count"], 0)
        self.assertEqual(trace["after"]["raw_archive_count"], 1)
        self.assertEqual(trace["trade_proposals_after"], 1)
        self.assertEqual(trace["ownership_after"].get("Daniel"), "user:donny")
        archives = list_draft_archives(session)
        self.assertEqual(archives[0]["draft_id"], "draft99")
        self.assertTrue(archives[0].get("repaired_from_context"))

    def test_repair_is_idempotent_no_duplicate_archives(self) -> None:
        from draft_archive_state import DRAFT_ARCHIVE_KEY, list_draft_archives

        session = bootstrap_session_for_workspace(
            "daniel",
            cloud_blob={**_context_store(), DRAFT_ARCHIVE_KEY: []},
        )
        session["_suite_auth_user_id"] = "user:donny"
        shared = _shared_doc()
        first = repair_workspace_session_for_league(session, league_id="league:test123", shared_doc=shared)
        second = repair_workspace_session_for_league(session, league_id="league:test123", shared_doc=shared)
        self.assertEqual(first["after"]["raw_archive_count"], 1)
        self.assertEqual(second["after"]["raw_archive_count"], 1)
        self.assertTrue(second.get("skipped_duplicate"))
        self.assertEqual(second["archives_repaired"], 0)
        self.assertEqual(len(list_draft_archives(session)), 1)

    def test_build_context_from_shared_assigns_workspace_team(self) -> None:
        ctx = build_context_from_shared_for_workspace(
            _shared_doc(),
            owner_user_id="user:seal11",
            existing=None,
        )
        self.assertEqual(ctx.get("my_team_name"), "Team 2")
        self.assertEqual(ctx["workflow"]["trade_proposals"][0]["trade_id"], "trade-1")

    def test_merge_repaired_workflow_preserves_unrelated_blob_keys(self) -> None:
        blob = {"active_page": "Fantasy Lineup Assistant", "comparison_state": {"players": ["A"]}}
        session = {"draft_archive_teams": [{"draft_id": "draft99"}], "comparison_state": {"players": ["B"]}}
        merged = merge_repaired_workflow_into_blob(blob, session)
        self.assertEqual(merged["active_page"], "Fantasy Lineup Assistant")
        self.assertEqual(merged["draft_archive_teams"][0]["draft_id"], "draft99")
        self.assertEqual(merged["comparison_state"]["players"], ["A"])

    @patch("fantasy_admin_draft_archive_repair.save_cloud_workflow_blob")
    @patch("fantasy_admin_draft_archive_repair.verify_cloud_workflow_readback")
    @patch("fantasy_admin_draft_archive_repair.load_cloud_workflow_blob")
    def test_run_repair_writes_and_verifies_readback(
        self,
        mock_load: unittest.mock.MagicMock,
        mock_verify: unittest.mock.MagicMock,
        mock_save: unittest.mock.MagicMock,
    ) -> None:
        from draft_archive_state import DRAFT_ARCHIVE_KEY

        mock_load.return_value = (
            {**_context_store(my_team="Daniel"), DRAFT_ARCHIVE_KEY: [], "_suite_auth_user_id": "user:donny"},
            "baseball__daniel",
        )
        mock_save.return_value = (True, "", "baseball__daniel")
        mock_verify.return_value = {"draft_archive_count": 1, "active_draft_archive_id": "draft99"}

        trace = run_league_draft_archive_repair(
            league_id="league:test123",
            workspaces=("daniel",),
            dry_run=False,
            write_disk=False,
        )
        self.assertTrue(trace["ok"])
        self.assertTrue(trace["workspace_results"][0]["cloud_write_ok"])
        self.assertTrue(trace["workspace_results"][0]["readback_verified"])
        mock_save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
