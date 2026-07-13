"""Simulator/Live override must win over saved Active League for all core workflow pages."""

from __future__ import annotations

import unittest

import pandas as pd

from fantasy_context_source import (
    USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY,
    USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
    WORKFLOW_SOURCE_ACTIVE,
    WORKFLOW_SOURCE_TEMPORARY_SIMULATOR,
    collect_saved_vs_effective_source_diagnostics,
    fantasy_workflow_using_html,
    invalidate_fantasy_workflow_descriptor_cache,
    resolve_fantasy_workflow_source_descriptor,
)
from fantasy_league_context import (
    CONTEXT_TYPE_REAL_LEAGUE,
    CREATION_ORIGIN_VALIDATED_IMPORT,
    upsert_league_context,
)
from resolved_fantasy_context import resolve_fantasy_context_for_page


UPLOAD = "3ce50b4f2e8b"
UPLOAD_CTX = "archive:3ce50b4f2e8b"


def _upload_rosters() -> dict:
    return {
        "Daniel": {"players": [{"name": f"U{i}"} for i in range(3)]},
        "Team 2": {"players": [{"name": f"T2{i}"} for i in range(2)]},
        "Team 3": {"players": [{"name": f"T3{i}"} for i in range(2)]},
        "Team 4": {"players": [{"name": f"T4{i}"} for i in range(2)]},
    }


def _simulator_board(*, picks: int = 20) -> pd.DataFrame:
    rows = []
    for i in range(picks):
        team = "Donny" if i % 2 == 0 else "Team B"
        rows.append(
            {
                "Round": (i // 2) + 1,
                "Pick": i + 1,
                "Team": team,
                "Player": f"SimPlayer{i}",
            }
        )
    return pd.DataFrame(rows)


def _seed_upload_active(*, room_your_team: str = "Daniel") -> dict:
    rosters = _upload_rosters()
    session: dict = {
        "_suite_auth_user_id": "daniel",
        "_suite_auth_external_id": "ext-daniel",
        "_suite_active_workspace_id": "daniel",
        "active_draft_archive_id": UPLOAD,
        "room_your_team": room_your_team,
        USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY: False,
        USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY: False,
        "draft_archive_teams": [
            {
                "draft_id": UPLOAD,
                "draft_name": "Upload Test Demo",
                "draft_type": "imported_league",
                "creation_origin": CREATION_ORIGIN_VALIDATED_IMPORT,
                "league_context_id": UPLOAD_CTX,
                "team_name": "Daniel",
                "players": list(rosters["Daniel"]["players"]),
                "league_rosters": rosters,
                "content_revision": 3,
            }
        ],
        "fantasy_league_context_state": {
            "active_league_context_id": UPLOAD_CTX,
            "contexts": {},
        },
        "draft_room_table": _simulator_board(picks=20),
        "_draft_simulator_resume_identity": {
            "kind": "simulator",
            "user_team": "Donny",
            "pick_count": 20,
        },
    }
    upsert_league_context(
        session,
        {
            "league_context_id": UPLOAD_CTX,
            "context_type": CONTEXT_TYPE_REAL_LEAGUE,
            "display_name": "Upload Test Demo",
            "league_name": "Upload Test Demo",
            "creation_origin": CREATION_ORIGIN_VALIDATED_IMPORT,
            "my_team_name": "Daniel",
            "metadata": {
                "creation_origin": CREATION_ORIGIN_VALIDATED_IMPORT,
                "source_draft_id": UPLOAD,
            },
            "league_rosters": rosters,
        },
    )
    return session


class EffectiveSourceOverridePriorityTests(unittest.TestCase):
    def test_simulator_override_on_with_saved_upload(self) -> None:
        session = _seed_upload_active(room_your_team="Daniel")
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = True
        invalidate_fantasy_workflow_descriptor_cache(session)

        desc = resolve_fantasy_workflow_source_descriptor(session)
        self.assertEqual(desc["source_kind"], WORKFLOW_SOURCE_TEMPORARY_SIMULATOR)
        self.assertEqual(desc["league_context_id"], "__ephemeral_simulator__")
        self.assertEqual(desc["my_team_name"], "Donny")
        self.assertEqual(set(desc["team_names"]), {"Donny", "Team B"})
        self.assertEqual(desc["draft_id"], "")
        self.assertEqual(desc["board_pick_count"], 20)
        self.assertTrue(desc["is_temporary_source"])
        self.assertNotIn("Upload Test Demo", str(desc.get("display_name") or ""))
        self.assertNotIn("Daniel", desc["team_names"])
        self.assertNotIn("Team 2", desc["team_names"])

        resolved = resolve_fantasy_context_for_page(session, force=True)
        self.assertTrue(str(resolved.source_kind).startswith("temporary"))
        self.assertEqual(resolved.active_league_context_id, "__ephemeral_simulator__")
        self.assertEqual(resolved.active_draft_id, "")
        self.assertEqual(resolved.canonical_league_id, "")
        self.assertEqual(resolved.active_team_name, "Donny")
        self.assertEqual(set(resolved.team_names), {"Donny", "Team B"})
        self.assertEqual(len((resolved.league_rosters.get("Donny") or {}).get("players") or []), 10)
        self.assertTrue(resolved.coherent)

        html = fantasy_workflow_using_html(session)
        self.assertIn("Temporary Practice Board", html)
        self.assertIn("Draft Room Simulator", html)
        self.assertIn("Donny", html)
        self.assertNotIn("Upload Test Demo", html)
        self.assertNotIn("Active League", html)

        layers = collect_saved_vs_effective_source_diagnostics(session)
        self.assertEqual(layers["saved_active_name"], "Upload Test Demo")
        self.assertEqual(layers["saved_active_draft_id"], UPLOAD)
        self.assertEqual(layers["saved_active_team"], "Daniel")
        self.assertEqual(layers["effective_source_kind"], WORKFLOW_SOURCE_TEMPORARY_SIMULATOR)
        self.assertEqual(layers["effective_context_id"], "__ephemeral_simulator__")
        self.assertEqual(layers["effective_team"], "Donny")
        self.assertEqual(set(layers["effective_roster_team_names"]), {"Donny", "Team B"})
        self.assertEqual(layers["effective_board_pick_count"], 20)

        # Saved selection unchanged.
        self.assertEqual(session.get("active_draft_archive_id"), UPLOAD)
        self.assertEqual(
            session["fantasy_league_context_state"]["active_league_context_id"],
            UPLOAD_CTX,
        )

    def test_override_off_restores_upload(self) -> None:
        session = _seed_upload_active()
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = True
        resolve_fantasy_workflow_source_descriptor(session)

        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        invalidate_fantasy_workflow_descriptor_cache(session)
        desc = resolve_fantasy_workflow_source_descriptor(session)
        self.assertEqual(desc["source_kind"], WORKFLOW_SOURCE_ACTIVE)
        self.assertEqual(desc["league_context_id"], UPLOAD_CTX)
        self.assertEqual(desc["draft_id"], UPLOAD)
        self.assertEqual(desc["my_team_name"], "Daniel")
        self.assertEqual(set(desc["team_names"]), {"Daniel", "Team 2", "Team 3", "Team 4"})

        resolved = resolve_fantasy_context_for_page(session, force=True)
        self.assertEqual(resolved.active_draft_id, UPLOAD)
        self.assertEqual(resolved.active_team_name, "Daniel")
        self.assertEqual(set(resolved.team_names), {"Daniel", "Team 2", "Team 3", "Team 4"})
        self.assertEqual(len((resolved.league_rosters.get("Daniel") or {}).get("players") or []), 3)

        html = fantasy_workflow_using_html(session)
        self.assertIn("Upload Test Demo", html)
        self.assertIn("Daniel", html)
        self.assertNotIn("Temporary Practice Board", html)

    def test_repeated_toggle_atomic(self) -> None:
        session = _seed_upload_active()
        fingerprints: list[str] = []
        for enabled in (False, True, False, True):
            session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = enabled
            invalidate_fantasy_workflow_descriptor_cache(session)
            desc = resolve_fantasy_workflow_source_descriptor(session)
            resolved = resolve_fantasy_context_for_page(session, force=True)
            fingerprints.append(resolved.context_fingerprint)
            if enabled:
                self.assertEqual(desc["source_kind"], WORKFLOW_SOURCE_TEMPORARY_SIMULATOR)
                self.assertEqual(desc["my_team_name"], "Donny")
                self.assertEqual(resolved.active_league_context_id, "__ephemeral_simulator__")
                self.assertEqual(set(resolved.team_names), {"Donny", "Team B"})
            else:
                self.assertEqual(desc["source_kind"], WORKFLOW_SOURCE_ACTIVE)
                self.assertEqual(desc["my_team_name"], "Daniel")
                self.assertEqual(resolved.active_draft_id, UPLOAD)
                self.assertEqual(set(resolved.team_names), {"Daniel", "Team 2", "Team 3", "Team 4"})
        # ON/OFF states are distinct; identical toggle states match.
        self.assertEqual(fingerprints[1], fingerprints[3])
        self.assertEqual(fingerprints[0], fingerprints[2])
        self.assertNotEqual(fingerprints[0], fingerprints[1])

    def test_cross_page_descriptor_agreement(self) -> None:
        session = _seed_upload_active()
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = True
        invalidate_fantasy_workflow_descriptor_cache(session)
        desc = resolve_fantasy_workflow_source_descriptor(session)
        resolved = resolve_fantasy_context_for_page(session, force=True)
        # Core pages share one descriptor/resolved context fingerprint.
        for _page in (
            "Fantasy Lineup Assistant",
            "Fantasy Standings Tracker",
            "Waiver Wire",
            "Trades",
        ):
            again = resolve_fantasy_workflow_source_descriptor(session)
            self.assertEqual(again["source_kind"], desc["source_kind"])
            self.assertEqual(again["my_team_name"], desc["my_team_name"])
            self.assertEqual(again["team_names"], desc["team_names"])
            self.assertEqual(again["league_context_id"], desc["league_context_id"])
            self.assertEqual(again["descriptor_cache_fingerprint"], desc["descriptor_cache_fingerprint"])
        self.assertEqual(resolved.active_team_name, desc["my_team_name"])
        self.assertEqual(list(resolved.team_names), list(desc["team_names"]))

    def test_descriptor_cache_invalidates_on_override(self) -> None:
        session = _seed_upload_active()
        first = resolve_fantasy_workflow_source_descriptor(session)
        first_fp = session.get("_workflow_descriptor_fp")
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = True
        second = resolve_fantasy_workflow_source_descriptor(session)
        self.assertNotEqual(session.get("_workflow_descriptor_fp"), first_fp)
        self.assertNotEqual(first["source_kind"], second["source_kind"])
        self.assertEqual(second["source_kind"], WORKFLOW_SOURCE_TEMPORARY_SIMULATOR)


class EffectiveSourceCrossDeviceOverrideTests(unittest.TestCase):
    def test_override_pref_sync_flips_effective_source(self) -> None:
        from account_fantasy_preferences import (
            install_test_cloud_store,
            sync_account_fantasy_preferences,
            write_account_fantasy_preferences,
        )
        from fantasy_context_ui import (
            _SIM_CONTEXT_TOGGLE_WIDGET_KEY,
            apply_simulator_override_toggle_from_widget,
        )

        store: dict = {}
        install_test_cloud_store(store)
        phone = _seed_upload_active()
        phone["_suite_device_id"] = "phone"
        phone["_suite_auth_user_id"] = "daniel"
        write_account_fantasy_preferences(phone)

        phone[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = True
        apply_simulator_override_toggle_from_widget(phone)
        self.assertTrue(phone.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))
        phone_desc = resolve_fantasy_workflow_source_descriptor(phone)
        self.assertEqual(phone_desc["source_kind"], WORKFLOW_SOURCE_TEMPORARY_SIMULATOR)

        dell = _seed_upload_active()
        dell["_suite_device_id"] = "dell"
        dell["_suite_auth_user_id"] = "daniel"
        dell[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        sync_account_fantasy_preferences(dell, force=True)
        self.assertTrue(dell.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))
        dell["draft_room_table"] = _simulator_board(picks=20)
        dell["_draft_simulator_resume_identity"] = {
            "kind": "simulator",
            "user_team": "Donny",
            "pick_count": 20,
        }
        invalidate_fantasy_workflow_descriptor_cache(dell)
        dell_desc = resolve_fantasy_workflow_source_descriptor(dell)
        self.assertEqual(dell_desc["source_kind"], WORKFLOW_SOURCE_TEMPORARY_SIMULATOR)
        self.assertEqual(dell_desc["my_team_name"], "Donny")
        html = fantasy_workflow_using_html(dell)
        self.assertIn("Temporary Practice Board", html)

        dell[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = False
        apply_simulator_override_toggle_from_widget(dell)
        sync_account_fantasy_preferences(phone, force=True)
        invalidate_fantasy_workflow_descriptor_cache(phone)
        phone_off = resolve_fantasy_workflow_source_descriptor(phone)
        self.assertEqual(phone_off["source_kind"], WORKFLOW_SOURCE_ACTIVE)
        self.assertEqual(phone_off["my_team_name"], "Daniel")
        install_test_cloud_store(None)

if __name__ == "__main__":
    unittest.main()
