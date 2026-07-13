"""Regression tests for coherent fantasy workflow page headers."""

from __future__ import annotations

import unittest

from draft_archive_state import ACTIVE_DRAFT_ARCHIVE_KEY, DRAFT_ARCHIVE_KEY, DRAFT_TYPE_IMPORTED, DRAFT_TYPE_LIVE
from fantasy_context_source import (
    get_effective_fantasy_context,
    resolve_fantasy_workflow_source_descriptor,
)
from fantasy_league_context import (
    FANTASY_LEAGUE_CONTEXT_STATE_KEY,
    context_id_for_archive,
    get_active_league_context,
    upsert_league_context,
)


def _session() -> dict:
    return {
        DRAFT_ARCHIVE_KEY: [],
        ACTIVE_DRAFT_ARCHIVE_KEY: "",
        FANTASY_LEAGUE_CONTEXT_STATE_KEY: {"contexts": {}, "active_league_context_id": ""},
        "room_your_team": "Donny",
    }


def _robins_context(*, my_team: str = "Donny") -> dict:
    draft_id = "c6810611c73e"
    return {
        "league_context_id": context_id_for_archive(draft_id),
        "context_type": "live_draft_result",
        "display_name": "Robins Fantasy — Donny vs Team B",
        "league_name": "Robins Fantasy",
        "my_team_name": my_team,
        "source": "live_draft_room",
        "metadata": {
            "source_draft_id": draft_id,
            "creation_origin": "live_draft_room",
            "league_id": "league:robins",
        },
        "team_ownership": {
            "Donny": {"user_id": "user:daniel", "external_id": "daniel"},
            "Team B": {"user_id": "user:coakley11", "external_id": "coakley11"},
        },
        "league_rosters": {
            "Donny": {"players": [{"player_name": f"D{i}"} for i in range(10)]},
            "Team B": {"players": [{"player_name": f"B{i}"} for i in range(10)]},
        },
    }


class FantasyWorkflowHeaderCoherenceTests(unittest.TestCase):
    def test_stale_upload_archive_name_does_not_override_robins_header(self) -> None:
        session = _session()
        session["_suite_auth_user_id"] = "user:daniel"
        session["_suite_auth_external_id"] = "daniel"
        robins = _robins_context(my_team="Donny")
        upload_id = "3ce50b4f2e8b"
        upsert_league_context(session, robins)
        session[FANTASY_LEAGUE_CONTEXT_STATE_KEY]["active_league_context_id"] = robins["league_context_id"]
        session[DRAFT_ARCHIVE_KEY] = [
            {
                "draft_id": upload_id,
                "draft_name": "Upload Test Demo",
                "draft_type": DRAFT_TYPE_IMPORTED,
                "league_context_id": context_id_for_archive(upload_id),
            },
            {
                "draft_id": "c6810611c73e",
                "draft_name": "Robins Fantasy — Donny vs Team B",
                "draft_type": DRAFT_TYPE_LIVE,
                "league_context_id": robins["league_context_id"],
            },
        ]
        session[ACTIVE_DRAFT_ARCHIVE_KEY] = upload_id

        data_ctx = get_active_league_context(session)
        desc = resolve_fantasy_workflow_source_descriptor(session)
        assert data_ctx is not None
        self.assertEqual(desc["league_context_id"], data_ctx["league_context_id"])
        self.assertEqual(desc["draft_id"], "c6810611c73e")
        self.assertEqual(desc["display_name"], "Robins Fantasy")
        self.assertEqual(desc["my_team_name"], "Donny")
        self.assertIn("Live Draft", desc["subtitle"])
        self.assertIn("Donny vs Team B", desc["subtitle"])
        self.assertNotIn("Upload Test Demo", desc["display_name"])

    def test_coakley11_resolves_team_b(self) -> None:
        session = _session()
        ctx = _robins_context(my_team="Team B")
        upsert_league_context(session, ctx)
        session[FANTASY_LEAGUE_CONTEXT_STATE_KEY]["active_league_context_id"] = ctx["league_context_id"]
        session["_suite_auth_user_id"] = "user:coakley11"
        session["_suite_auth_external_id"] = "coakley11"
        session["room_your_team"] = "Donny"
        desc = resolve_fantasy_workflow_source_descriptor(session)
        self.assertEqual(desc["my_team_name"], "Team B")

    def test_header_ids_match_data_context(self) -> None:
        session = _session()
        session["_suite_auth_user_id"] = "user:daniel"
        session["_suite_auth_external_id"] = "daniel"
        ctx = _robins_context()
        upsert_league_context(session, ctx)
        session[FANTASY_LEAGUE_CONTEXT_STATE_KEY]["active_league_context_id"] = ctx["league_context_id"]
        session[ACTIVE_DRAFT_ARCHIVE_KEY] = "c6810611c73e"
        session[DRAFT_ARCHIVE_KEY] = [
            {
                "draft_id": "c6810611c73e",
                "draft_name": "Robins Fantasy — Donny vs Team B",
                "draft_type": DRAFT_TYPE_LIVE,
                "league_context_id": ctx["league_context_id"],
            }
        ]
        data_ctx = get_active_league_context(session)
        desc = resolve_fantasy_workflow_source_descriptor(session)
        assert data_ctx is not None
        self.assertEqual(desc["league_context_id"], data_ctx["league_context_id"])
        from fantasy_league_identity import resolve_canonical_league_id

        self.assertEqual(desc["canonical_league_id"], str(resolve_canonical_league_id(data_ctx) or ""))


class WorkflowDescriptorCacheTests(unittest.TestCase):
    def test_descriptor_cached_until_fingerprint_changes(self) -> None:
        session = _session()
        session["_suite_auth_user_id"] = "user:daniel"
        ctx = _robins_context()
        upsert_league_context(session, ctx)
        session[FANTASY_LEAGUE_CONTEXT_STATE_KEY]["active_league_context_id"] = ctx["league_context_id"]
        first = resolve_fantasy_workflow_source_descriptor(session)
        cached_obj = session.get("_workflow_descriptor_cached")
        first_fp = session.get("_workflow_descriptor_fp")
        second = resolve_fantasy_workflow_source_descriptor(session)
        self.assertIs(session.get("_workflow_descriptor_cached"), cached_obj)
        self.assertEqual(first, second)
        session["room_your_team"] = "Team B"
        third = resolve_fantasy_workflow_source_descriptor(session)
        self.assertNotEqual(session.get("_workflow_descriptor_fp"), first_fp)
        self.assertIsNot(session.get("_workflow_descriptor_cached"), cached_obj)
        self.assertIsInstance(third, dict)


if __name__ == "__main__":
    unittest.main()
