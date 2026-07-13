"""Cross-device account preference sync — shared fake cloud store (no stubbed docs)."""

from __future__ import annotations

import copy
import unittest

from account_fantasy_preferences import (
    PREFS_DOC_KEY,
    SESSION_APPLIED_REV_KEY,
    activate_library_selection_and_sync_preferences,
    install_test_cloud_store,
    load_preference_revision_meta,
    prefs_settings_app,
    sync_account_fantasy_preferences,
    write_account_fantasy_preferences,
)
from fantasy_context_source import (
    USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY,
    USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
)
from fantasy_context_ui import (
    FANTASY_RESEARCH_SYNC_KEY,
    _RESEARCH_SYNC_TOGGLE_WIDGET_KEY,
    _SIM_CONTEXT_TOGGLE_WIDGET_KEY,
    reseed_fantasy_context_toggle_widgets,
)
from fantasy_league_context import (
    CONTEXT_TYPE_LIVE_DRAFT_RESULT,
    CONTEXT_TYPE_REAL_LEAGUE,
    CREATION_ORIGIN_LIVE_DRAFT_ROOM,
    CREATION_ORIGIN_VALIDATED_IMPORT,
    ensure_fantasy_league_context_state,
    upsert_league_context,
)


ROBINS_DRAFT = "c6810611c73e"
ROBINS_CTX = "archive:c6810611c73e"
UPLOAD_DRAFT = "3ce50b4f2e8b"
UPLOAD_CTX = "archive:3ce50b4f2e8b"


def _seed_session(*, user_id: str = "daniel", workspace: str = "daniel", device: str = "phone") -> dict:
    session: dict = {
        "_suite_auth_user_id": user_id,
        "_suite_auth_external_id": f"ext-{user_id}",
        "_suite_active_workspace_id": workspace,
        "_suite_device_id": device,
        "draft_archive_teams": [
            {
                "draft_id": ROBINS_DRAFT,
                "draft_name": "Robins Fantasy",
                "draft_type": "live_draft_room",
                "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM,
                "league_context_id": ROBINS_CTX,
                "players": [{"name": f"R{i}"} for i in range(10)],
                "teams": ["Donny", "Team B"],
            },
            {
                "draft_id": UPLOAD_DRAFT,
                "draft_name": "Upload Test Demo",
                "draft_type": "imported_league",
                "creation_origin": CREATION_ORIGIN_VALIDATED_IMPORT,
                "league_context_id": UPLOAD_CTX,
                "players": [{"name": f"U{i}"} for i in range(4)],
                "teams": ["A", "B", "C", "D"],
            },
        ],
        "active_draft_archive_id": ROBINS_DRAFT,
        "fantasy_league_context_state": {
            "active_league_context_id": ROBINS_CTX,
            "contexts": {},
        },
        FANTASY_RESEARCH_SYNC_KEY: False,
        USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY: False,
        USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY: False,
        SESSION_APPLIED_REV_KEY: 0,
    }
    upsert_league_context(
        session,
        {
            "league_context_id": ROBINS_CTX,
            "context_type": CONTEXT_TYPE_LIVE_DRAFT_RESULT,
            "display_name": "Robins Fantasy",
            "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM,
            "metadata": {
                "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM,
                "source_draft_id": ROBINS_DRAFT,
            },
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
            "metadata": {
                "creation_origin": CREATION_ORIGIN_VALIDATED_IMPORT,
                "source_draft_id": UPLOAD_DRAFT,
            },
            "league_rosters": {"A": [], "B": [], "C": [], "D": []},
        },
        mark_persist_authoritative=False,
    )
    ensure_fantasy_league_context_state(session)["active_league_context_id"] = ROBINS_CTX
    return session


def _cloud_doc(store: dict, session: dict) -> dict:
    app = prefs_settings_app(session)
    envelope = store.get(app) or {}
    doc = envelope.get(PREFS_DOC_KEY) or {}
    return copy.deepcopy(doc) if isinstance(doc, dict) else {}


class CrossDevicePreferenceSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store: dict[str, dict] = {}
        install_test_cloud_store(self.store)

    def tearDown(self) -> None:
        install_test_cloud_store(None)

    def test_atomic_activate_writes_upload_not_robins(self) -> None:
        phone = _seed_session(device="phone")
        write_account_fantasy_preferences(phone, reason="bootstrap")
        bootstrap = _cloud_doc(self.store, phone)
        self.assertEqual(bootstrap.get("active_draft_id"), ROBINS_DRAFT)

        result = activate_library_selection_and_sync_preferences(
            phone,
            draft_id=UPLOAD_DRAFT,
            reason="activate_archive",
        )
        self.assertTrue(result.get("ok"))
        prefs = result.get("prefs_write") or {}
        self.assertTrue(prefs.get("write_verified"))

        readback = _cloud_doc(self.store, phone)
        self.assertEqual(readback.get("active_draft_id"), UPLOAD_DRAFT)
        self.assertEqual(readback.get("active_league_context_id"), UPLOAD_CTX)
        self.assertNotEqual(readback.get("active_draft_id"), ROBINS_DRAFT)
        self.assertEqual(int(readback.get("revision") or 0), int(bootstrap.get("revision") or 0) + 1)

    def test_dell_fragment_applies_phone_activation(self) -> None:
        phone = _seed_session(device="phone")
        dell = _seed_session(device="dell")
        write_account_fantasy_preferences(phone, reason="bootstrap")
        # Share applied rev so Dell starts aligned.
        sync_account_fantasy_preferences(dell, force=True)

        activate_library_selection_and_sync_preferences(phone, draft_id=UPLOAD_DRAFT)
        meta = load_preference_revision_meta(dell)
        self.assertGreater(int(meta.get("revision") or 0), int(dell.get(SESSION_APPLIED_REV_KEY) or 0))

        applied = sync_account_fantasy_preferences(dell, force=True)
        self.assertTrue(applied.get("applied"))
        self.assertEqual(dell.get("active_draft_archive_id"), UPLOAD_DRAFT)
        store = ensure_fantasy_league_context_state(dell)
        self.assertEqual(store.get("active_league_context_id"), UPLOAD_CTX)

    def test_toggle_callbacks_sync_and_reseed_widgets(self) -> None:
        phone = _seed_session(device="phone")
        dell = _seed_session(device="dell")
        write_account_fantasy_preferences(phone, reason="bootstrap")
        sync_account_fantasy_preferences(dell, force=True)

        phone[FANTASY_RESEARCH_SYNC_KEY] = True
        phone[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = True
        phone[_RESEARCH_SYNC_TOGGLE_WIDGET_KEY] = True
        phone[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = True
        write = write_account_fantasy_preferences(phone, reason="fantasy_context_toggle")
        self.assertTrue(write.get("write_verified"))
        doc = _cloud_doc(self.store, phone)
        self.assertTrue(doc.get("research_mode_enabled"))
        self.assertEqual(doc.get("fantasy_source_override_kind"), "simulator_board")
        # Selecting Upload separately must not clear Research Mode.
        activate_library_selection_and_sync_preferences(phone, draft_id=UPLOAD_DRAFT)
        doc2 = _cloud_doc(self.store, phone)
        self.assertTrue(doc2.get("research_mode_enabled"))
        self.assertEqual(doc2.get("fantasy_source_override_kind"), "simulator_board")

        sync_account_fantasy_preferences(dell, force=True)
        self.assertTrue(dell.get(FANTASY_RESEARCH_SYNC_KEY))
        self.assertTrue(dell.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))
        reseed_fantasy_context_toggle_widgets(dell)
        self.assertTrue(dell.get(_RESEARCH_SYNC_TOGGLE_WIDGET_KEY))
        self.assertTrue(dell.get(_SIM_CONTEXT_TOGGLE_WIDGET_KEY))

    def test_reverse_direction_dell_to_phone(self) -> None:
        phone = _seed_session(device="phone")
        dell = _seed_session(device="dell")
        write_account_fantasy_preferences(phone, reason="bootstrap")
        sync_account_fantasy_preferences(dell, force=True)
        activate_library_selection_and_sync_preferences(phone, draft_id=UPLOAD_DRAFT)
        phone[FANTASY_RESEARCH_SYNC_KEY] = True
        phone[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = True
        write_account_fantasy_preferences(phone, reason="toggles")
        sync_account_fantasy_preferences(dell, force=True)

        activate_library_selection_and_sync_preferences(dell, draft_id=ROBINS_DRAFT)
        dell[FANTASY_RESEARCH_SYNC_KEY] = False
        dell[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        write_account_fantasy_preferences(dell, reason="reverse")

        sync_account_fantasy_preferences(phone, force=True)
        self.assertEqual(phone.get("active_draft_archive_id"), ROBINS_DRAFT)
        self.assertFalse(phone.get(FANTASY_RESEARCH_SYNC_KEY))
        self.assertFalse(phone.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))
        reseed_fantasy_context_toggle_widgets(phone)
        self.assertFalse(phone.get(_RESEARCH_SYNC_TOGGLE_WIDGET_KEY))
        self.assertFalse(phone.get(_SIM_CONTEXT_TOGGLE_WIDGET_KEY))

    def test_refresh_and_reboot_restore_latest(self) -> None:
        phone = _seed_session(device="phone")
        write_account_fantasy_preferences(phone, reason="bootstrap")
        activate_library_selection_and_sync_preferences(phone, draft_id=UPLOAD_DRAFT)
        phone[FANTASY_RESEARCH_SYNC_KEY] = True
        write_account_fantasy_preferences(phone, reason="research")

        # Simulated new browser session / reboot — empty applied revision.
        rebooted = _seed_session(device="phone")
        rebooted[SESSION_APPLIED_REV_KEY] = 0
        sync_account_fantasy_preferences(rebooted, force=True)
        self.assertEqual(rebooted.get("active_draft_archive_id"), UPLOAD_DRAFT)
        self.assertTrue(rebooted.get(FANTASY_RESEARCH_SYNC_KEY))

    def test_accounts_isolated(self) -> None:
        daniel = _seed_session(user_id="daniel", device="phone")
        coakley = _seed_session(user_id="coakley11", workspace="coakley11", device="dell")
        # Distinct workspace => distinct settings app keys for non-daniel profiles.
        write_account_fantasy_preferences(daniel, reason="bootstrap")
        write_account_fantasy_preferences(coakley, reason="bootstrap")
        activate_library_selection_and_sync_preferences(daniel, draft_id=UPLOAD_DRAFT)

        daniel_doc = _cloud_doc(self.store, daniel)
        coakley_doc = _cloud_doc(self.store, coakley)
        self.assertEqual(daniel_doc.get("active_draft_id"), UPLOAD_DRAFT)
        self.assertEqual(coakley_doc.get("active_draft_id"), ROBINS_DRAFT)
        self.assertNotEqual(prefs_settings_app(daniel), prefs_settings_app(coakley))

    def test_stale_local_cannot_overwrite_newer_cloud(self) -> None:
        session = _seed_session()
        write_account_fantasy_preferences(session, reason="bootstrap")
        activate_library_selection_and_sync_preferences(session, draft_id=UPLOAD_DRAFT)
        cloud_rev = int(_cloud_doc(self.store, session).get("revision") or 0)
        session[SESSION_APPLIED_REV_KEY] = 1
        session["active_draft_archive_id"] = ROBINS_DRAFT
        ensure_fantasy_league_context_state(session)["active_league_context_id"] = ROBINS_CTX
        trace = write_account_fantasy_preferences(session, reason="stale", expected_revision=1)
        self.assertEqual(trace.get("conflict"), "cloud_newer")
        self.assertEqual(int(_cloud_doc(self.store, session).get("revision") or 0), cloud_rev)


if __name__ == "__main__":
    unittest.main()
