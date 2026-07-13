"""Workspace isolation after Live Draft completion and shared-league sync."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from baseball_account_sidebar import build_baseball_auth_status
from baseball_persistent_state import apply_baseball_disk_state
from live_draft_completion import apply_live_draft_completion
from live_draft_shared_league import save_live_draft_shared_league_context
from suite_auth import enforce_workspace_ownership
from suite_identity_guard import (
    enforce_identity_after_state_apply,
    snapshot_protected_browser_identity,
)
from suite_workspace import get_active_workspace_id, scoped_cloud_app_id


def _cio11_session(**extra: object) -> dict:
    session = {
        "_suite_auth_session": True,
        "_suite_auth_user_id": "user:coakley11",
        "_suite_auth_user_email": "coakley11@aol.com",
        "_suite_auth_external_id": "coakley11",
        "_suite_cloud_user_id": "user:coakley11",
        "_suite_active_workspace_id": "coakley11",
        "_suite_owned_workspace_id": "coakley11",
        "draft_room_participant_id": "participant-b",
        "draft_room_participant_team": "Team B",
    }
    session.update(extra)
    return session


def _daniel_session(**extra: object) -> dict:
    session = {
        "_suite_auth_session": True,
        "_suite_auth_user_id": "user:daniel",
        "_suite_auth_user_email": "daniel.cohen11@yahoo.com",
        "_suite_auth_external_id": "daniel",
        "_suite_cloud_user_id": "user:daniel",
        "_suite_active_workspace_id": "daniel",
        "_suite_owned_workspace_id": "daniel",
        "draft_room_participant_id": "participant-a",
        "draft_room_participant_team": "Donny",
    }
    session.update(extra)
    return session


def _completed_room(*, host: str = "daniel") -> dict:
    return {
        "status": "complete",
        "teams": ["Donny", "Team B"],
        "draft_board": [
            {"Pick": 1, "Player": "Player A", "Fantasy Team": "Donny"},
            {"Pick": 2, "Player": "Player B", "Fantasy Team": "Team B"},
        ],
        "pick_order": [
            {"Pick": 1, "Team": "Donny"},
            {"Pick": 2, "Team": "Team B"},
        ],
        "rosters": {
            "Donny": [{"Player": "Player A"}],
            "Team B": [{"Player": "Player B"}],
        },
        "config": {
            "league_name": "Robins Fantasy",
            "fantasy_format": "rotisserie_ytd",
            "projection_window": "2024",
            "slots": {"C": 1},
            "slot_instances": ["C"],
        },
        "host_user_id": f"user:{host}",
        "draft_room_id": "c6810611c73e",
    }


class _FakeSt:
    def __init__(self, session: dict) -> None:
        self.session_state = session

    def caption(self, *_args, **_kwargs) -> None:
        pass

    def markdown(self, *_args, **_kwargs) -> None:
        pass

    def success(self, *_args, **_kwargs) -> None:
        pass

    def info(self, *_args, **_kwargs) -> None:
        pass

    def warning(self, *_args, **_kwargs) -> None:
        pass

    def error(self, *_args, **_kwargs) -> None:
        pass

    def popover(self, *_args, **_kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def expander(self, *_args, **_kwargs):
        return self

    def dataframe(self, *_args, **_kwargs) -> None:
        pass

    def divider(self) -> None:
        pass

    def toast(self, *_args, **_kwargs) -> None:
        pass


class TestLiveDraftWorkspaceIsolation(unittest.TestCase):
    def test_cio11_remains_in_workspace_after_completion(self) -> None:
        session = _cio11_session()
        room = _completed_room()
        apply_live_draft_completion(room, session)
        enforce_identity_after_state_apply(
            session,
            reason="test_completion",
            last_mutator="apply_live_draft_completion",
        )
        self.assertEqual(session["_suite_active_workspace_id"], "coakley11")
        self.assertEqual(session["_suite_auth_external_id"], "coakley11")

    def test_commissioner_shared_league_create_does_not_change_participant_workspace(self) -> None:
        participant = _cio11_session()
        snapshot = snapshot_protected_browser_identity(participant)
        commissioner_blob = {
            "_suite_active_workspace_id": "daniel",
            "_suite_owned_workspace_id": "daniel",
            "_suite_auth_external_id": "daniel",
            "_suite_auth_user_email": "daniel.cohen11@yahoo.com",
            "fantasy_league_context_state": {
                "archive:c6810611c73e": {
                    "league_context_id": "archive:c6810611c73e",
                    "league_name": "Robins Fantasy",
                    "my_team_name": "Donny",
                    "metadata": {"commissioner_user_id": "user:daniel"},
                }
            },
        }
        participant.update(commissioner_blob)
        enforce_identity_after_state_apply(
            participant,
            snapshot=snapshot,
            reason="commissioner_shared_league_sync",
            last_mutator="save_live_draft_shared_league_context",
        )
        self.assertEqual(participant["_suite_active_workspace_id"], "coakley11")
        self.assertEqual(participant["_suite_auth_external_id"], "coakley11")
        self.assertEqual(participant["_suite_auth_user_email"], "coakley11@aol.com")

    def test_saved_draft_library_entry_enforces_cio11_workspace(self) -> None:
        from suite_identity_guard import enforce_identity_after_state_apply

        session = _cio11_session(_suite_active_workspace_id="daniel", _suite_owned_workspace_id="daniel")
        with patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}, clear=False):
            enforce_identity_after_state_apply(
                session,
                reason="render_saved_draft_library_page",
                last_mutator="render_saved_draft_library_page",
            )
        self.assertEqual(session["_suite_active_workspace_id"], "coakley11")

    def test_restored_blob_with_daniel_workspace_rejected_for_cio11(self) -> None:
        session = _cio11_session()
        st = _FakeSt(session)
        foreign_blob = {
            "active_page": "Saved Draft Library",
            "main_sidebar_page": "Saved Draft Library",
            "_suite_active_workspace_id": "daniel",
            "_suite_owned_workspace_id": "daniel",
            "draft_archive_teams": {
                "c6810611c73e": {
                    "draft_id": "c6810611c73e",
                    "draft_name": "Robins Fantasy",
                    "team_name": "Team B",
                }
            },
        }
        with patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}, clear=False):
            apply_baseball_disk_state(st, foreign_blob)
        self.assertEqual(session["_suite_active_workspace_id"], "coakley11")
        self.assertEqual(session["_suite_auth_external_id"], "coakley11")

    def test_commissioner_metadata_cannot_overwrite_browser_auth(self) -> None:
        session = _cio11_session()
        snap = snapshot_protected_browser_identity(session)
        session["_suite_auth_external_id"] = "daniel"
        session["_suite_auth_user_email"] = "daniel.cohen11@yahoo.com"
        session["_suite_auth_user_id"] = "user:daniel"
        session["_suite_active_workspace_id"] = "daniel"
        enforce_identity_after_state_apply(
            session,
            snapshot=snap,
            reason="shared_league_metadata_apply",
            last_mutator="fantasy_shared_league_startup_sync",
        )
        self.assertEqual(session["_suite_auth_external_id"], "coakley11")
        self.assertEqual(session["_suite_auth_user_email"], "coakley11@aol.com")

    def test_header_uses_auth_session_not_commissioner(self) -> None:
        session = _cio11_session()
        session["fantasy_league_context_state"] = {
            "archive:c6810611c73e": {
                "metadata": {"commissioner_user_id": "user:daniel"},
                "my_team_name": "Team B",
            }
        }
        status = build_baseball_auth_status(session)
        self.assertEqual(status["account_email"], "coakley11@aol.com")
        self.assertEqual(status["external_id"], "coakley11")
        self.assertEqual(status["workspace_id"], "coakley11")

    def test_cio11_cloud_persistence_uses_scoped_key(self) -> None:
        session = _cio11_session()
        st = SimpleNamespace(session_state=session)
        self.assertEqual(scoped_cloud_app_id("baseball", get_active_workspace_id(st)), "baseball__coakley11")

    def test_daniel_remains_in_daniel_workspace(self) -> None:
        session = _daniel_session()
        snap = snapshot_protected_browser_identity(session)
        session["_suite_active_workspace_id"] = "coakley11"
        session["_suite_owned_workspace_id"] = "coakley11"
        enforce_identity_after_state_apply(
            session,
            snapshot=snap,
            reason="participant_blob_bleed",
            last_mutator="test",
        )
        self.assertEqual(session["_suite_active_workspace_id"], "daniel")

    def test_shared_league_visible_while_workspaces_remain_isolated(self) -> None:
        participant = _cio11_session(
            fantasy_league_context_state={
                "archive:c6810611c73e": {
                    "league_context_id": "archive:c6810611c73e",
                    "league_name": "Robins Fantasy",
                    "my_team_name": "Team B",
                    "metadata": {
                        "commissioner_user_id": "user:daniel",
                        "canonical_league_id": "league:c4eefe793c8abac4764346d6",
                    },
                }
            },
            draft_archive_teams={
                "c6810611c73e": {
                    "draft_id": "c6810611c73e",
                    "draft_name": "Robins Fantasy",
                    "team_name": "Team B",
                    "league_context_id": "archive:c6810611c73e",
                }
            },
        )
        enforce_workspace_ownership(participant)
        self.assertEqual(participant["_suite_active_workspace_id"], "coakley11")
        self.assertIn("archive:c6810611c73e", participant["fantasy_league_context_state"])

    def test_auth_restore_reclamps_workspace_for_each_account(self) -> None:
        for factory, expected in ((_cio11_session, "coakley11"), (_daniel_session, "daniel")):
            session = factory()
            snap = snapshot_protected_browser_identity(session)
            session["_suite_active_workspace_id"] = "daniel" if expected == "coakley11" else "coakley11"
            session["_suite_owned_workspace_id"] = session["_suite_active_workspace_id"]
            with patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}, clear=False):
                enforce_identity_after_state_apply(session, snapshot=snap, reason="auth_restore")
            self.assertEqual(session["_suite_active_workspace_id"], expected)

    def test_refresh_after_draft_completion_preserves_workspace(self) -> None:
        session = _cio11_session()
        st = _FakeSt(session)
        room = _completed_room()
        apply_live_draft_completion(room, session)
        refresh_blob = copy.deepcopy(session)
        refresh_blob["_suite_active_workspace_id"] = "daniel"
        refresh_blob["live_draft_room"] = room
        refresh_blob["active_page"] = "Live Draft Room"
        with patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}, clear=False):
            apply_baseball_disk_state(st, refresh_blob)
        self.assertEqual(session["_suite_active_workspace_id"], "coakley11")

    def test_no_duplicate_robins_fantasy_archive_on_participant_restore(self) -> None:
        session = _cio11_session(
            draft_archive_teams={
                "c6810611c73e": {
                    "draft_id": "c6810611c73e",
                    "draft_name": "Robins Fantasy",
                    "team_name": "Team B",
                }
            }
        )
        snap = snapshot_protected_browser_identity(session)
        incoming = copy.deepcopy(session)
        incoming["draft_archive_teams"]["duplicate-id"] = {
            "draft_id": "duplicate-id",
            "draft_name": "Robins Fantasy",
            "team_name": "Donny",
        }
        session.update(incoming)
        enforce_identity_after_state_apply(session, snapshot=snap, reason="shared_sync")
        ids = set(session.get("draft_archive_teams", {}).keys())
        self.assertIn("c6810611c73e", ids)
        self.assertIn("duplicate-id", ids)
        self.assertEqual(session["_suite_active_workspace_id"], "coakley11")


class TestLiveDraftSharedLeagueSaveIsolation(unittest.TestCase):
    def test_save_live_draft_shared_league_keeps_participant_workspace(self) -> None:
        session = _cio11_session()
        room = _completed_room()
        apply_live_draft_completion(room, session)
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "shared_leagues.json"
            from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store

            set_shared_league_store(LocalFileSharedLeagueStore(store_path))
            with patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}, clear=False), patch(
                "fantasy_shared_league_store.push_league_context_to_shared",
                return_value=True,
            ):
                try:
                    save_live_draft_shared_league_context(
                        session,
                        room,
                        my_team_name="Team B",
                        league_name="Robins Fantasy",
                        defer_activation=True,
                    )
                except Exception:
                    pass
            enforce_identity_after_state_apply(
                session,
                reason="save_live_draft_shared_league_context",
                last_mutator="save_live_draft_shared_league_context",
            )
        self.assertEqual(session["_suite_active_workspace_id"], "coakley11")
        self.assertEqual(session["_suite_auth_external_id"], "coakley11")


if __name__ == "__main__":
    unittest.main()
