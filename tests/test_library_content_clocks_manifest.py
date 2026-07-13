"""Saved Draft Library content_updated_at + compact manifest cross-device tests."""

from __future__ import annotations

import copy
import unittest

from account_fantasy_preferences import (
    activate_library_selection_and_sync_preferences,
    install_test_cloud_store as install_prefs_cloud,
    sync_account_fantasy_preferences,
    write_account_fantasy_preferences,
)
from draft_archive_state import format_archive_modified, rename_draft_archive
from draft_library_manifest import (
    install_test_manifest_cloud_store,
    publish_library_manifest_to_cloud,
    repair_polluted_identical_content_clocks,
    sync_library_manifest_from_cloud,
)
from fantasy_context_ui import (
    FANTASY_RESEARCH_SYNC_KEY,
    _RESEARCH_SYNC_TOGGLE_WIDGET_KEY,
    _SIM_CONTEXT_TOGGLE_WIDGET_KEY,
    apply_research_mode_toggle_from_widget,
    apply_simulator_override_toggle_from_widget,
)
from fantasy_league_context import (
    CONTEXT_TYPE_LIVE_DRAFT_RESULT,
    CONTEXT_TYPE_REAL_LEAGUE,
    CREATION_ORIGIN_LIVE_DRAFT_ROOM,
    CREATION_ORIGIN_VALIDATED_IMPORT,
    ensure_fantasy_league_context_state,
    upsert_league_context,
)


UPLOAD = "3ce50b4f2e8b"
UPLOAD_CTX = "archive:3ce50b4f2e8b"
ROBINS = "c6810611c73e"
ROBINS_CTX = "archive:c6810611c73e"
UPLOAD_CONTENT_AT = "2026-07-13T16:10:00+00:00"
ROBINS_CONTENT_AT = "2026-07-13T15:40:00+00:00"


def _seed(*, device: str) -> dict:
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
                "created_at": "2026-07-10T12:00:00+00:00",
                "updated_at": UPLOAD_CONTENT_AT,
                "content_updated_at": UPLOAD_CONTENT_AT,
                "content_revision": 3,
                "players": [{"name": "U1"}],
                "teams": ["A", "B"],
            },
            {
                "draft_id": ROBINS,
                "draft_name": "Robins Fantasy",
                "draft_type": "live_draft_room",
                "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM,
                "league_context_id": ROBINS_CTX,
                "league_id": "league:c4eefe793c8abac4764346d6",
                "created_at": "2026-07-01T12:00:00+00:00",
                "updated_at": ROBINS_CONTENT_AT,
                "content_updated_at": ROBINS_CONTENT_AT,
                "content_revision": 5,
                "players": [{"name": "R1"}],
                "teams": ["Donny", "Team B"],
            },
        ],
        "active_draft_archive_id": ROBINS,
        "fantasy_league_context_state": {
            "active_league_context_id": ROBINS_CTX,
            "contexts": {},
        },
        FANTASY_RESEARCH_SYNC_KEY: False,
    }
    upsert_league_context(
        session,
        {
            "league_context_id": ROBINS_CTX,
            "context_type": CONTEXT_TYPE_LIVE_DRAFT_RESULT,
            "display_name": "Robins Fantasy",
            "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM,
            "metadata": {"source_draft_id": ROBINS},
            "league_rosters": {"Donny": [], "Team B": []},
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
            "metadata": {"source_draft_id": UPLOAD},
            "league_rosters": {"A": [], "B": []},
        },
        mark_persist_authoritative=False,
    )
    ensure_fantasy_league_context_state(session)["active_league_context_id"] = ROBINS_CTX
    return session


def _clocks(session: dict) -> dict[str, str]:
    out = {}
    for row in session.get("draft_archive_teams") or []:
        out[str(row.get("draft_id"))] = str(row.get("content_updated_at") or "")
    return out


class LibraryContentClockManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store: dict[str, dict] = {}
        install_prefs_cloud(self.store)
        install_test_manifest_cloud_store(self.store)

    def tearDown(self) -> None:
        install_prefs_cloud(None)
        install_test_manifest_cloud_store(None)

    def test_identical_manifest_across_devices(self) -> None:
        phone = _seed(device="phone")
        dell = _seed(device="dell")
        publish_library_manifest_to_cloud(phone)
        sync_library_manifest_from_cloud(dell, force=True)
        self.assertEqual(_clocks(phone), _clocks(dell))
        self.assertEqual(_clocks(phone)[UPLOAD], UPLOAD_CONTENT_AT)
        self.assertEqual(_clocks(phone)[ROBINS], ROBINS_CONTENT_AT)
        # Refresh / warm sync must not rewrite.
        before = copy.deepcopy(_clocks(dell))
        sync_library_manifest_from_cloud(dell)
        self.assertEqual(_clocks(dell), before)

    def test_set_active_does_not_change_content_clocks(self) -> None:
        phone = _seed(device="phone")
        dell = _seed(device="dell")
        write_account_fantasy_preferences(phone, reason="bootstrap")
        publish_library_manifest_to_cloud(phone)
        sync_account_fantasy_preferences(dell, force=True)
        sync_library_manifest_from_cloud(dell, force=True)
        before = copy.deepcopy(_clocks(phone))
        activate_library_selection_and_sync_preferences(phone, draft_id=UPLOAD)
        self.assertEqual(_clocks(phone), before)
        sync_account_fantasy_preferences(dell, force=True)
        self.assertEqual(dell.get("active_draft_archive_id"), UPLOAD)
        self.assertEqual(_clocks(dell), before)

    def test_toggles_do_not_change_content_clocks(self) -> None:
        phone = _seed(device="phone")
        dell = _seed(device="dell")
        write_account_fantasy_preferences(phone, reason="bootstrap")
        publish_library_manifest_to_cloud(phone)
        sync_account_fantasy_preferences(dell, force=True)
        before = copy.deepcopy(_clocks(phone))
        phone[_RESEARCH_SYNC_TOGGLE_WIDGET_KEY] = True
        phone[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = True
        apply_research_mode_toggle_from_widget(phone)
        apply_simulator_override_toggle_from_widget(phone)
        sync_account_fantasy_preferences(dell, force=True)
        self.assertEqual(_clocks(phone), before)
        self.assertEqual(_clocks(dell), before)

    def test_rename_bumps_only_that_record(self) -> None:
        phone = _seed(device="phone")
        dell = _seed(device="dell")
        publish_library_manifest_to_cloud(phone)
        sync_library_manifest_from_cloud(dell, force=True)
        before_robins = _clocks(phone)[ROBINS]
        rename_draft_archive(phone, UPLOAD, "Upload Test Demo Renamed")
        self.assertNotEqual(_clocks(phone)[UPLOAD], UPLOAD_CONTENT_AT)
        self.assertEqual(_clocks(phone)[ROBINS], before_robins)
        sync_library_manifest_from_cloud(dell, force=True)
        self.assertEqual(_clocks(dell)[UPLOAD], _clocks(phone)[UPLOAD])
        self.assertEqual(_clocks(dell)[ROBINS], before_robins)
        self.assertIn("Jul", format_archive_modified(phone["draft_archive_teams"][0]))

    def test_hydration_does_not_rewrite_content_clocks(self) -> None:
        session = _seed(device="phone")
        before = copy.deepcopy(_clocks(session))
        for row in session["draft_archive_teams"]:
            row["last_local_hydration_at"] = "2026-07-13T17:27:00+00:00"
            # Hydration path historically stamped updated_at — content clocks must stay.
            row["updated_at"] = "2026-07-13T17:27:00+00:00"
        from fantasy_admin_draft_archive_repair import _sync_archives_to_workspace_team

        ctx = ensure_fantasy_league_context_state(session)["contexts"].get(UPLOAD_CTX) or {
            "league_context_id": UPLOAD_CTX,
            "my_team_name": "A",
            "draft_id": UPLOAD,
            "metadata": {"source_draft_id": UPLOAD},
            "league_rosters": {"A": {"players": []}},
        }
        ctx["my_team_name"] = "A"
        ctx["league_rosters"] = {"A": {"players": []}}
        _sync_archives_to_workspace_team(session, ctx)
        self.assertEqual(_clocks(session)[UPLOAD], before[UPLOAD])

    def test_repair_polluted_identical_stamps(self) -> None:
        session = _seed(device="dell")
        polluted = "2026-07-13T17:27:00+00:00"
        for row in session["draft_archive_teams"]:
            row["content_updated_at"] = polluted
            row["updated_at"] = polluted
            row["content_revision"] = 1
        repaired = repair_polluted_identical_content_clocks(session)
        self.assertGreaterEqual(repaired, 1)
        clocks = _clocks(session)
        self.assertNotEqual(clocks[UPLOAD], clocks[ROBINS])
        self.assertEqual(clocks[UPLOAD], "2026-07-10T12:00:00+00:00")
        self.assertEqual(clocks[ROBINS], "2026-07-01T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
