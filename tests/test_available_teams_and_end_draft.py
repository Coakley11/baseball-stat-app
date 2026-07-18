"""Available-team authority + End Draft restore tombstone regressions."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import join_shared_draft_room
from draft_room_participant_state import restore_persisted_shared_room_membership
from draft_room_shared_state import LocalFileSharedRoomStore, reset_shared_room_store_for_tests
from draft_room_state import should_resolve_live_draft_source
from live_draft_completion import (
    END_DRAFT_CLEAR_KEYS,
    ENDED_DRAFT_IDS_KEY,
    ENDED_ROOM_CODES_KEY,
    end_live_draft_session,
    is_live_draft_ended_tombstoned,
)
from live_draft_setup_mode import SETUP_MODE_SHARED, finalize_shared_room_create, set_live_draft_setup_mode
from live_draft_state import LIVE_DRAFT_ROOM_KEY, LIVE_DRAFT_STATE_KEY, prepare_live_draft_state
from live_draft_team_ownership import (
    list_available_shared_room_teams,
    lookup_open_teams_for_code,
    open_teams_for_join,
)
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_ID_KEY
from user_page_preferences import PAGE_KEY_LIVE_DRAFT_SETUP, get_user_page_preferences
from live_draft_setup_mode import get_live_draft_setup_mode


def _sample_room() -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Juan Soto", "Primary Position": "OF"},
        ]
    )
    return {
        "draft_room_id": "AVAIL1",
        "status": "not_started",
        "current_pick_index": 0,
        "config": {
            "num_teams": 2,
            "your_team": "Team A",
            "user_team": "Team A",
            "teams": ["Team A", "Team B"],
            "draft_setup_mode": SETUP_MODE_SHARED,
        },
        "teams": ["Team A", "Team B"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team A"},
            {"Pick": 2, "Round": 1, "Team": "Team B"},
        ],
        "draft_board": [],
        "rosters": {"Team A": [], "Team B": []},
        "drafted_player_ids": [],
        "pool": pool,
    }


def _daniel() -> dict:
    return {
        AUTH_USER_ID_KEY: "uuid-daniel",
        AUTH_EXTERNAL_ID_KEY: "daniel",
        "_suite_cloud_user_id": "cloud-daniel-alias",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "daniel",
        "_suite_owned_workspace_id": "daniel",
        "draft_room_participant_id": "uuid-daniel",
        "live_draft_setup_mode": SETUP_MODE_SHARED,
    }


def _coakley() -> dict:
    return {
        AUTH_USER_ID_KEY: "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        AUTH_EXTERNAL_ID_KEY: "coakley11",
        "_suite_cloud_user_id": "cloud-coakley-alias",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "coakley11",
        "_suite_owned_workspace_id": "coakley11",
        "draft_room_participant_id": "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        "live_draft_setup_mode": SETUP_MODE_SHARED,
    }


class AvailableTeamsAliasTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)
        self._auth = mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
        self._auth.start()
        self._auth_enabled = mock.patch("suite_auth.is_auth_enabled", return_value=True)
        self._auth_enabled.start()
        self._authenticated = mock.patch("suite_auth.is_authenticated", return_value=True)
        self._authenticated.start()

    def tearDown(self) -> None:
        self._authenticated.stop()
        self._auth_enabled.stop()
        self._auth.stop()
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def test_duplicate_host_aliases_leave_team_b_open(self) -> None:
        """Daniel aliases claiming Team A + Team B must not hide Team B from Coakley11."""
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(host, _sample_room(), host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        doc = self.store.load(code)
        assert isinstance(doc, dict)
        # Stale presence / dual-id bug: same host identity under two keys, second seat Team B.
        participants = dict(doc.get("participants") or {})
        participants["cloud-daniel-alias"] = {
            "assigned_team": "Team B",
            "display_name": "Daniel",
            "user_id": "uuid-daniel",
            "account_user_id": "uuid-daniel",
        }
        doc["host_user_id"] = "cloud-daniel-alias"
        doc["host_participant_id"] = "uuid-daniel"
        doc["participants"] = participants
        self.store.save(doc)

        available, diag = list_available_shared_room_teams(doc, "guest-coakley")
        self.assertEqual(available, ["Team B"], diag)
        team_b = (diag.get("occupancy") or {}).get("Team B") or {}
        self.assertTrue(team_b.get("available"))
        self.assertEqual(team_b.get("reason"), "open")
        # Raw alias still listed for diagnostics, but not as canonical claimant.
        self.assertIn("cloud-daniel-alias", team_b.get("claimant_raw_ids") or [])
        self.assertFalse(team_b.get("canonical_participant_id"))

        guest = _coakley()
        teams, lookup_err = lookup_open_teams_for_code(code, store=self.store, session=guest)
        self.assertFalse(lookup_err, lookup_err)
        self.assertEqual(teams, ["Team B"])
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)

    def test_stale_coakley_claim_offers_reenter_not_no_teams(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(host, _sample_room(), host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        guest = _coakley()
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)

        # Fresh guest browser with same identity — already owns Team B.
        guest2 = _coakley()
        teams, lookup_err = lookup_open_teams_for_code(code, store=self.store, session=guest2)
        self.assertEqual(teams, [])
        self.assertIn("already joined", lookup_err.lower())
        self.assertIn("Team B", lookup_err)
        self.assertNotEqual(lookup_err, "No teams are available")
        claim = guest2.get("_draft_room_claim_diag") or {}
        self.assertEqual(claim.get("already_joined_team"), "Team B")


class EndDraftRestoreTests(unittest.TestCase):
    def test_end_draft_clears_runtime_and_blocks_restore(self) -> None:
        session = {
            AUTH_USER_ID_KEY: "uuid-daniel",
            "workspace_id": "daniel",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            "active_shared_draft_room_code": "ENDRM1",
            LIVE_DRAFT_ROOM_KEY: {
                "status": "complete",
                "draft_room_id": "room-end-avail",
                "config": {
                    "league_name": "Ended Shared",
                    "draft_setup_mode": SETUP_MODE_SHARED,
                    "user_team": "Team A",
                },
                "teams": ["Team A", "Team B"],
                "draft_board": [
                    {"Pick": 1, "Team": "Team A", "Player": "Aaron Judge"},
                    {"Pick": 2, "Team": "Team B", "Player": "Juan Soto"},
                ],
                "current_pick_index": 2,
                "live_draft_completion_record": {
                    "draft_status": "complete",
                    "final_board_locked": True,
                },
                "meta": {"sync": {"room_code": "ENDRM1"}},
            },
            LIVE_DRAFT_STATE_KEY: {
                "status": "complete",
                "draft_room_id": "room-end-avail",
                "draft_board": [{"Pick": 1, "Team": "Team A", "Player": "Aaron Judge"}],
            },
            "page_filter_state": {
                "Live Draft Room": {
                    "live_draft_room": {
                        "status": "complete",
                        "draft_room_id": "room-end-avail",
                        "draft_board": [{"Pick": 1, "Team": "Team A", "Player": "Aaron Judge"}],
                        "_persist_schema": 1,
                        "pool_records": [],
                    }
                },
                "_user_page_preferences": {
                    PAGE_KEY_LIVE_DRAFT_SETUP: {
                        "user_id": "uuid-daniel",
                        "workspace_id": "daniel",
                        "settings": {
                            "live_draft_setup_mode": SETUP_MODE_SHARED,
                            "live_draft_team_count": 2,
                            "live_draft_timer": "30 seconds",
                        },
                    }
                },
            },
            "draft_room_participant_membership": {
                "ENDRM1": {
                    "uuid-daniel": {"assigned_team": "Team A", "joined_at": "2026-07-01T00:00:00+00:00"}
                }
            },
        }
        with mock.patch("live_draft_state.commit_live_draft_room", return_value={"saved": True}):
            with mock.patch("draft_room_shared_state.load_shared_room", return_value=None):
                result = end_live_draft_session(session, st=None, reason="test_end")
        self.assertTrue(result.get("ok"))
        self.assertIsNone(session.get(LIVE_DRAFT_ROOM_KEY))
        self.assertFalse(session.get(LIVE_DRAFT_STATE_KEY))
        self.assertTrue(is_live_draft_ended_tombstoned(session, room_code="ENDRM1"))
        self.assertTrue(is_live_draft_ended_tombstoned(session, draft_room_id="room-end-avail"))
        self.assertIn("ENDRM1", session.get(ENDED_ROOM_CODES_KEY) or [])
        self.assertIn("room-end-avail", session.get(ENDED_DRAFT_IDS_KEY) or [])
        self.assertEqual(get_live_draft_setup_mode(session), SETUP_MODE_SHARED)
        prefs = get_user_page_preferences("uuid-daniel", "daniel", PAGE_KEY_LIVE_DRAFT_SETUP, session=session)
        self.assertEqual(prefs.get("live_draft_setup_mode"), SETUP_MODE_SHARED)

        # Refresh / prepare must not reopen completed board.
        session[LIVE_DRAFT_STATE_KEY] = {
            "status": "complete",
            "draft_room_id": "room-end-avail",
            "draft_board": [{"Pick": 1, "Team": "Team A", "Player": "Aaron Judge"}],
            "_persist_schema": 1,
            "pool_records": [],
        }
        room = prepare_live_draft_state(session)
        self.assertIsNone(room)
        self.assertFalse(should_resolve_live_draft_source(session))

        # Membership restore must not revive ended room.
        session["active_shared_draft_room_code"] = "ENDRM1"
        restored = restore_persisted_shared_room_membership(session)
        self.assertEqual(restored, "")

        # Cleared key contract includes core runtime pointers.
        for key in (
            "active_shared_draft_room_code",
            "draft_room_participant_team",
            "live_draft_my_team",
        ):
            self.assertIn(key, END_DRAFT_CLEAR_KEYS)

    def test_end_preserves_per_user_setup_prefs(self) -> None:
        daniel = {
            AUTH_USER_ID_KEY: "uuid-daniel",
            "workspace_id": "daniel",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            "live_draft_team_count": 4,
            LIVE_DRAFT_ROOM_KEY: {
                "status": "in_progress",
                "draft_room_id": "pref-d1",
                "config": {"draft_setup_mode": SETUP_MODE_SHARED},
                "draft_board": [{"Pick": 1}],
            },
            "page_filter_state": {
                "_user_page_preferences": {
                    PAGE_KEY_LIVE_DRAFT_SETUP: {
                        "user_id": "uuid-daniel",
                        "workspace_id": "daniel",
                        "settings": {
                            "live_draft_setup_mode": SETUP_MODE_SHARED,
                            "live_draft_team_count": 4,
                            "live_draft_timer": "60 seconds",
                        },
                    }
                }
            },
        }
        coakley = {
            AUTH_USER_ID_KEY: "uuid-coakley",
            "workspace_id": "coakley11",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            LIVE_DRAFT_ROOM_KEY: {
                "status": "in_progress",
                "draft_room_id": "pref-c1",
                "config": {"draft_setup_mode": SETUP_MODE_SHARED},
                "draft_board": [{"Pick": 1}],
            },
            "page_filter_state": {
                "_user_page_preferences": {
                    PAGE_KEY_LIVE_DRAFT_SETUP: {
                        "user_id": "uuid-coakley",
                        "workspace_id": "coakley11",
                        "settings": {
                            "live_draft_setup_mode": SETUP_MODE_SHARED,
                            "live_draft_team_count": 2,
                            "live_draft_timer": "30 seconds",
                        },
                    }
                }
            },
        }
        with mock.patch("live_draft_state.commit_live_draft_room", return_value={"saved": True}):
            end_live_draft_session(daniel, st=None, reason="end_d")
            end_live_draft_session(coakley, st=None, reason="end_c")
        self.assertEqual(get_live_draft_setup_mode(daniel), SETUP_MODE_SHARED)
        self.assertEqual(get_live_draft_setup_mode(coakley), SETUP_MODE_SHARED)
        d_prefs = get_user_page_preferences("uuid-daniel", "daniel", PAGE_KEY_LIVE_DRAFT_SETUP, session=daniel)
        c_prefs = get_user_page_preferences("uuid-coakley", "coakley11", PAGE_KEY_LIVE_DRAFT_SETUP, session=coakley)
        self.assertEqual(d_prefs.get("live_draft_timer"), "60 seconds")
        self.assertEqual(c_prefs.get("live_draft_timer"), "30 seconds")
        self.assertEqual(d_prefs.get("live_draft_team_count"), 4)
        self.assertEqual(c_prefs.get("live_draft_team_count"), 2)


if __name__ == "__main__":
    unittest.main()
