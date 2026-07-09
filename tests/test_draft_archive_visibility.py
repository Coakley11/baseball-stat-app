"""Tests for Saved Draft Library visibility isolation."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from draft_archive_state import DRAFT_TYPE_IMPORTED, list_draft_archives
from draft_archive_visibility import (
    is_saved_draft_visible_to_session,
    list_visible_draft_archives,
    prune_invisible_shared_league_state,
)
from fantasy_league_context import (
    CONTEXT_TYPE_REAL_LEAGUE,
    get_league_context,
    save_imported_league_context,
    upsert_league_context,
)
from fantasy_league_team_ownership import assign_team_owner_to_context
from tests.test_fantasy_trade_proposals import _as_user, _league_board
from workflow_persist_guard import _cloud_workflow_fallback_workspace_ids

_SHARED_DRAFT_CFG = {
    "fantasy_format": "5x5 Roto",
    "scoring_type": "Roto (5x5)",
    "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "UTIL": 1},
    "slot_instances": [],
}


def _auth_session(*, user_id: str, external_id: str, workspace: str) -> dict:
    return {
        "_suite_auth_session": True,
        "_suite_auth_user_id": f"jwt-{user_id}",
        "_suite_auth_user_email": f"{external_id}@example.com",
        "_suite_auth_external_id": external_id,
        "_suite_cloud_user_id": user_id,
        "_suite_active_workspace_id": workspace,
        "_suite_owned_workspace_id": workspace,
        "draft_shared_settings": dict(_SHARED_DRAFT_CFG),
    }


def _seed_daniel_shared_league(session: dict) -> dict:
    with _as_user("user:daniel"):
        _, context = save_imported_league_context(
            session,
            _league_board(),
            my_team_name="Donny",
            draft_name="Shared Upload league",
            league_name="Shared Upload league",
            config=_SHARED_DRAFT_CFG,
            save_only=True,
            assign_team=True,
        )
    return context


class TestDraftArchiveVisibility(unittest.TestCase):
    def test_commissioner_sees_uploaded_shared_league(self) -> None:
        session = _auth_session(user_id="user:daniel", external_id="daniel", workspace="daniel")
        context = _seed_daniel_shared_league(session)
        entry = list_draft_archives(session)[0]
        with _as_user("user:daniel"):
            self.assertTrue(is_saved_draft_visible_to_session(session, entry, context=context))
            self.assertEqual(len(list_visible_draft_archives(session)), 1)
        self.assertEqual(str(context.get("context_type") or ""), CONTEXT_TYPE_REAL_LEAGUE)

    def test_non_member_cannot_see_shared_league(self) -> None:
        session = _auth_session(user_id="user:daniel", external_id="daniel", workspace="daniel")
        _seed_daniel_shared_league(session)

        coakley = _auth_session(user_id="user:coakley", external_id="coakley11", workspace="coakley11")
        coakley["draft_archive_teams"] = list(session.get("draft_archive_teams") or [])
        coakley["fantasy_league_context_state"] = dict(session.get("fantasy_league_context_state") or {})

        with _as_user("user:coakley"):
            self.assertEqual(len(list_visible_draft_archives(coakley)), 0)
            entry = list_draft_archives(coakley)[0]
            context = get_league_context(coakley, str(entry.get("league_context_id") or ""))
            self.assertFalse(is_saved_draft_visible_to_session(coakley, entry, context=context))

    def test_prune_removes_leaked_shared_league(self) -> None:
        session = _auth_session(user_id="user:daniel", external_id="daniel", workspace="daniel")
        _seed_daniel_shared_league(session)

        coakley = _auth_session(user_id="user:coakley", external_id="coakley11", workspace="coakley11")
        coakley["draft_archive_teams"] = list(session.get("draft_archive_teams") or [])
        coakley["fantasy_league_context_state"] = dict(session.get("fantasy_league_context_state") or {})

        with _as_user("user:coakley"):
            removed = prune_invisible_shared_league_state(coakley)
        self.assertGreaterEqual(removed["archives_removed"], 1)
        self.assertGreaterEqual(removed["contexts_removed"], 1)
        self.assertEqual(len(list_draft_archives(coakley)), 0)

    def test_invited_member_sees_league_after_team_claim(self) -> None:
        session = _auth_session(user_id="user:daniel", external_id="daniel", workspace="daniel")
        context = _seed_daniel_shared_league(session)
        league_context_id = str(context.get("league_context_id") or "")

        coakley = _auth_session(user_id="user:coakley", external_id="coakley11", workspace="coakley11")
        coakley["draft_archive_teams"] = list(session.get("draft_archive_teams") or [])
        coakley["fantasy_league_context_state"] = dict(session.get("fantasy_league_context_state") or {})
        loaded = get_league_context(coakley, league_context_id) or context
        loaded = assign_team_owner_to_context(
            loaded,
            "Team 2",
            user_id="user:coakley",
            email="coakley11@aol.com",
            display_name="Coakley",
        )
        upsert_league_context(coakley, loaded)

        with _as_user("user:coakley"):
            self.assertEqual(len(list_visible_draft_archives(coakley)), 1)

    def test_coakley11_has_no_daniel_workspace_fallback(self) -> None:
        session = _auth_session(user_id="user:coakley", external_id="coakley11", workspace="coakley11")
        with patch("suite_auth.is_auth_enabled", return_value=True), patch(
            "suite_auth.is_authenticated", return_value=True
        ), patch("suite_workspace_registry.is_admin_account", return_value=False):
            self.assertEqual(_cloud_workflow_fallback_workspace_ids(session), [])


if __name__ == "__main__":
    unittest.main()
