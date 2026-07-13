"""Active-league context isolation — no hybrid Upload/Robins roster payloads."""

from __future__ import annotations

import copy
import unittest

import pandas as pd

from account_fantasy_preferences import (
    activate_library_selection_and_sync_preferences,
    install_test_cloud_store,
    invalidate_preference_dependent_caches,
    sync_account_fantasy_preferences,
    write_account_fantasy_preferences,
)
from fantasy_league_context import (
    CONTEXT_TYPE_LIVE_DRAFT_RESULT,
    CONTEXT_TYPE_REAL_LEAGUE,
    CREATION_ORIGIN_LIVE_DRAFT_ROOM,
    CREATION_ORIGIN_VALIDATED_IMPORT,
    ensure_fantasy_league_context_state,
    upsert_league_context,
)
from live_draft_navigation import get_draft_return_context
from resolved_fantasy_context import (
    resolve_fantasy_context_for_page,
    roster_dataframe_matches_resolved,
    validate_resolved_fantasy_context,
)


UPLOAD = "3ce50b4f2e8b"
UPLOAD_CTX = "archive:3ce50b4f2e8b"
ROBINS = "c6810611c73e"
ROBINS_CTX = "archive:c6810611c73e"
ROBINS_LEAGUE = "league:c4eefe793c8abac4764346d6"


def _players(n: int, prefix: str) -> list[dict]:
    return [{"name": f"{prefix}{i}", "Player": f"{prefix}{i}"} for i in range(n)]


def _seed(*, device: str = "phone") -> dict:
    upload_rosters = {
        "Daniel": {"players": _players(3, "U")},
        "Team 2": {"players": _players(2, "T2")},
        "Team 3": {"players": _players(2, "T3")},
        "Team 4": {"players": _players(2, "T4")},
    }
    robins_rosters = {
        "Donny": {"players": _players(10, "R")},
        "Team B": {"players": _players(8, "B")},
    }
    session: dict = {
        "_suite_auth_user_id": "daniel",
        "_suite_auth_external_id": "ext-daniel",
        "_suite_active_workspace_id": "daniel",
        "_suite_device_id": device,
        "draft_archive_teams": [
            {
                "draft_id": UPLOAD,
                "draft_name": "Upload Test Demo",
                "draft_type": "imported_league",
                "creation_origin": CREATION_ORIGIN_VALIDATED_IMPORT,
                "league_context_id": UPLOAD_CTX,
                "team_name": "Daniel",
                "players": copy.deepcopy(upload_rosters["Daniel"]["players"]),
                "league_rosters": copy.deepcopy(upload_rosters),
                "content_revision": 3,
            },
            {
                "draft_id": ROBINS,
                "draft_name": "Robins Fantasy",
                "draft_type": "live_draft_room",
                "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM,
                "league_context_id": ROBINS_CTX,
                "league_id": ROBINS_LEAGUE,
                "team_name": "Donny",
                "players": copy.deepcopy(robins_rosters["Donny"]["players"]),
                "league_rosters": copy.deepcopy(robins_rosters),
                "content_revision": 5,
            },
        ],
        "active_draft_archive_id": ROBINS,
        "room_your_team": "Donny",
        "fantasy_league_context_state": {"active_league_context_id": ROBINS_CTX, "contexts": {}},
    }
    upsert_league_context(
        session,
        {
            "league_context_id": ROBINS_CTX,
            "context_type": CONTEXT_TYPE_LIVE_DRAFT_RESULT,
            "display_name": "Robins Fantasy",
            "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM,
            "my_team_name": "Donny",
            "metadata": {
                "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM,
                "source_draft_id": ROBINS,
                "league_id": ROBINS_LEAGUE,
            },
            "league_rosters": copy.deepcopy(robins_rosters),
        },
        mark_persist_authoritative=False,
    )
    upsert_league_context(
        session,
        {
            "league_context_id": UPLOAD_CTX,
            "context_type": CONTEXT_TYPE_REAL_LEAGUE,
            "display_name": "Upload Test Demo",
            "creation_origin": CREATION_ORIGIN_VALIDATED_IMPORT,
            "my_team_name": "Daniel",
            "metadata": {
                "creation_origin": CREATION_ORIGIN_VALIDATED_IMPORT,
                "source_draft_id": UPLOAD,
            },
            "league_rosters": copy.deepcopy(upload_rosters),
        },
        mark_persist_authoritative=False,
    )
    ensure_fantasy_league_context_state(session)["active_league_context_id"] = ROBINS_CTX
    return session


def _stale_robins_roster_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Player": "R0", "Team": "Donny"},
            {"Player": "R1", "Team": "Donny"},
            {"Player": "B0", "Team": "Team B"},
        ]
    )


class ContextIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store: dict = {}
        install_test_cloud_store(self.store)

    def tearDown(self) -> None:
        install_test_cloud_store(None)

    def test_upload_active_rejects_robins_roster_cache(self) -> None:
        session = _seed()
        write_account_fantasy_preferences(session, reason="bootstrap")
        # Poison session with Robins roster view while activating Upload.
        session["fantasy_current_roster_stats"] = _stale_robins_roster_df()
        activate_library_selection_and_sync_preferences(session, draft_id=UPLOAD)
        self.assertIsNone(session.get("fantasy_current_roster_stats"))
        resolved = resolve_fantasy_context_for_page(session, force=True)
        self.assertTrue(resolved.coherent, resolved.coherence_error)
        self.assertEqual(resolved.active_draft_id, UPLOAD)
        self.assertEqual(resolved.active_team_name, "Daniel")
        self.assertEqual(set(resolved.team_names), {"Daniel", "Team 2", "Team 3", "Team 4"})
        self.assertNotIn("Donny", resolved.team_names)
        self.assertNotIn("Team B", resolved.league_rosters)
        self.assertEqual(len(resolved.league_rosters["Daniel"]["players"]), 3)
        self.assertFalse(roster_dataframe_matches_resolved(_stale_robins_roster_df(), resolved))

    def test_robins_active_rejects_upload_teams(self) -> None:
        session = _seed()
        activate_library_selection_and_sync_preferences(session, draft_id=ROBINS)
        resolved = resolve_fantasy_context_for_page(session, force=True)
        self.assertTrue(resolved.coherent, resolved.coherence_error)
        self.assertEqual(resolved.active_draft_id, ROBINS)
        self.assertEqual(resolved.active_team_name, "Donny")
        self.assertEqual(set(resolved.team_names), {"Donny", "Team B"})
        self.assertNotIn("Daniel", resolved.team_names)
        self.assertEqual(len(resolved.league_rosters["Donny"]["players"]), 10)

    def test_repeated_switching_stays_coherent(self) -> None:
        session = _seed()
        write_account_fantasy_preferences(session, reason="bootstrap")
        for draft_id, team, teams in (
            (UPLOAD, "Daniel", {"Daniel", "Team 2", "Team 3", "Team 4"}),
            (ROBINS, "Donny", {"Donny", "Team B"}),
            (UPLOAD, "Daniel", {"Daniel", "Team 2", "Team 3", "Team 4"}),
            (ROBINS, "Donny", {"Donny", "Team B"}),
        ):
            session["fantasy_current_roster_stats"] = _stale_robins_roster_df()
            activate_library_selection_and_sync_preferences(session, draft_id=draft_id)
            resolved = resolve_fantasy_context_for_page(session, force=True)
            self.assertTrue(resolved.coherent, resolved.coherence_error)
            self.assertEqual(resolved.active_draft_id, draft_id)
            self.assertEqual(resolved.active_team_name, team)
            self.assertEqual(set(resolved.team_names), teams)
            self.assertIsNone(session.get("fantasy_current_roster_stats"))

    def test_cross_device_activation_replaces_roster_context(self) -> None:
        phone = _seed(device="phone")
        dell = _seed(device="dell")
        write_account_fantasy_preferences(phone, reason="bootstrap")
        sync_account_fantasy_preferences(dell, force=True)
        dell["fantasy_current_roster_stats"] = _stale_robins_roster_df()
        activate_library_selection_and_sync_preferences(phone, draft_id=UPLOAD)
        sync_account_fantasy_preferences(dell, force=True)
        # Cloud apply should invalidate caches via invalidate_preference_dependent_caches.
        invalidate_preference_dependent_caches(dell)
        resolved = resolve_fantasy_context_for_page(dell, force=True)
        self.assertEqual(resolved.active_draft_id, UPLOAD)
        self.assertEqual(resolved.active_team_name, "Daniel")
        self.assertEqual(set(resolved.team_names), {"Daniel", "Team 2", "Team 3", "Team 4"})
        self.assertIsNone(dell.get("fantasy_current_roster_stats"))

    def test_validate_detects_hybrid(self) -> None:
        ok, err = validate_resolved_fantasy_context(
            active_team_name="Daniel",
            team_names=["Daniel", "Team 2", "Team 3", "Team 4"],
            league_rosters={"Donny": {"players": []}, "Team B": {"players": []}},
            active_draft_id=UPLOAD,
            context={"metadata": {"source_draft_id": UPLOAD}},
        )
        self.assertFalse(ok)
        self.assertIn("active_team_not_in_rosters", err)

    def test_simulator_resume_keeps_independent_team(self) -> None:
        session = _seed()
        # 20-pick Robins board residual; then activate Upload (room_your_team becomes Daniel).
        session["draft_room_table"] = pd.DataFrame(
            [{"Fantasy Team": "Donny", "Player": f"P{i}", "Pick": i + 1} for i in range(20)]
        )
        session["room_your_team"] = "Donny"
        first = get_draft_return_context(session)
        self.assertIsNotNone(first)
        self.assertEqual(first.get("user_team"), "Donny")
        session["room_your_team"] = "Daniel"
        activate_library_selection_and_sync_preferences(session, draft_id=UPLOAD)
        second = get_draft_return_context(session)
        self.assertIsNotNone(second)
        self.assertEqual(second.get("kind"), "simulator")
        self.assertEqual(second.get("user_team"), "Donny")
        self.assertEqual(second.get("return_page"), "Draft Room Simulator")
        self.assertIn("20", second.get("picks_label") or "")


if __name__ == "__main__":
    unittest.main()
