"""Saved Draft Library identity guard — no RecursionError, persisted context only."""

from __future__ import annotations

import inspect
import unittest

from draft_archive_state import ACTIVE_DRAFT_ARCHIVE_KEY, DRAFT_ARCHIVE_KEY, DRAFT_TYPE_LIVE
from draft_archive_ui import _render_saved_draft_library_page_body
from fantasy_league_context import (
    FANTASY_LEAGUE_CONTEXT_STATE_KEY,
    context_id_for_archive,
    get_active_league_context,
    upsert_league_context,
)


def _robins_session() -> dict:
    draft_id = "c6810611c73e"
    ctx = {
        "league_context_id": context_id_for_archive(draft_id),
        "display_name": "Robins Fantasy — Donny vs Team B",
        "my_team_name": "Donny",
        "metadata": {"source_draft_id": draft_id, "league_id": "league:robins"},
        "team_ownership": {
            "Donny": {"user_id": "user:daniel", "external_id": "daniel"},
            "Team B": {"user_id": "user:coakley11"},
        },
        "league_rosters": {"Donny": {"players": []}, "Team B": {"players": []}},
    }
    session = {
        DRAFT_ARCHIVE_KEY: [
            {
                "draft_id": draft_id,
                "draft_name": "Robins Fantasy",
                "draft_type": DRAFT_TYPE_LIVE,
                "league_context_id": ctx["league_context_id"],
            }
        ],
        ACTIVE_DRAFT_ARCHIVE_KEY: draft_id,
        FANTASY_LEAGUE_CONTEXT_STATE_KEY: {
            "active_league_context_id": ctx["league_context_id"],
            "contexts": {ctx["league_context_id"]: ctx},
        },
        "draft_room_participant_team": "Donny",
        "room_your_team": "Donny",
        "_suite_auth_user_id": "user:daniel",
        "_suite_auth_external_id": "daniel",
    }
    upsert_league_context(session, ctx)
    return session


class SavedDraftLibraryIdentityGuardTests(unittest.TestCase):
    def test_library_body_passes_persisted_context_to_identity_guard(self) -> None:
        source = inspect.getsource(_render_saved_draft_library_page_body)
        self.assertIn("prepare_saved_draft_library_active_selection", source)
        self.assertIn("league_context=_persisted_library_context", source)

    def test_identity_stack_does_not_recursion_error(self) -> None:
        session = _robins_session()
        ctx = get_active_league_context(session, respect_source_priority=False)
        from suite_identity_guard import enforce_identity_after_state_apply

        enforce_identity_after_state_apply(
            session,
            reason="test_saved_draft_library_identity",
            league_context=ctx if isinstance(ctx, dict) else None,
        )
        from fantasy_workspace_team_identity import apply_account_team_identity_to_session

        apply_account_team_identity_to_session(
            session,
            reason="test_saved_draft_library_identity",
            context=ctx if isinstance(ctx, dict) else None,
        )


if __name__ == "__main__":
    unittest.main()
