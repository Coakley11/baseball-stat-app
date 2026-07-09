"""Tests for shared uploaded league invite workflow."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from draft_archive_state import DRAFT_ARCHIVE_KEY, DRAFT_TYPE_IMPORTED, get_draft_archive, list_draft_archives
from fantasy_league_context import get_league_context, save_imported_league_context, upsert_league_context
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_league_invites import (
    INVITE_STATUS_ACCEPTED,
    INVITE_STATUS_PENDING,
    append_invite_to_inbox,
    build_commissioner_invite_panel_trace,
    commissioner_invite_context,
    create_league_invite,
    is_league_commissioner,
    join_shared_league_from_invite,
    list_pending_invites_for_session,
)
from fantasy_league_team_ownership import assign_team_owner_to_context, trades_enabled
from fantasy_shared_league_store import LocalFileSharedLeagueStore, load_shared_league, set_shared_league_store
from tests.test_fantasy_trade_proposals import _as_user
from tests.test_imported_shared_league import _sample_board


def _four_team_board() -> pd.DataFrame:
    return _sample_board()

_SHARED_DRAFT_CFG = {
    "fantasy_format": "5x5 Roto",
    "scoring_type": "Roto (5x5)",
    "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "UTIL": 1},
    "slot_instances": [],
}


def _seed_imported_league(session: dict, *, user_id: str, team: str = "Donny", workspace: str = "daniel") -> dict:
    session["draft_shared_settings"] = dict(_SHARED_DRAFT_CFG)
    session["_suite_owned_workspace_id"] = workspace
    with _as_user(user_id):
        _, context = save_imported_league_context(
            session,
            _four_team_board(),
            my_team_name=team,
            draft_name="Invite Test League",
            league_name="Invite Test League",
            config=_SHARED_DRAFT_CFG,
            save_only=True,
            assign_team=True,
        )
    return context


class TestFantasyLeagueInvites(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store_root = Path(self._tmp.name) / "shared"
        self.store_root.mkdir(parents=True, exist_ok=True)
        self.workspace_root = Path(self._tmp.name) / "workspaces"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        set_shared_league_store(LocalFileSharedLeagueStore(root=self.store_root))

        def _test_workspace_dir(workspace_id: str | None = None) -> Path:
            from suite_workspace import normalize_workspace_id

            ws = normalize_workspace_id(workspace_id)
            path = self.workspace_root / ws
            path.mkdir(parents=True, exist_ok=True)
            return path

        self._workspace_dir_patcher = patch("suite_workspace.workspace_dir", side_effect=_test_workspace_dir)
        self._workspace_dir_patcher.start()
        self._registry_backup = None
        try:
            from suite_workspace_registry import REGISTRY_FILE

            if REGISTRY_FILE.is_file():
                self._registry_backup = REGISTRY_FILE.read_text(encoding="utf-8")
        except ImportError:
            pass

    def tearDown(self) -> None:
        self._workspace_dir_patcher.stop()
        set_shared_league_store(None)
        self._tmp.cleanup()
        try:
            from suite_workspace_registry import REGISTRY_FILE

            if self._registry_backup is not None:
                REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
                REGISTRY_FILE.write_text(self._registry_backup, encoding="utf-8")
            elif REGISTRY_FILE.is_file():
                REGISTRY_FILE.unlink()
        except OSError:
            pass

    def _write_registry(self, payload: dict) -> None:
        from suite_workspace_registry import REGISTRY_FILE

        REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        REGISTRY_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @contextmanager
    def _workspace(self, workspace_id: str):
        with patch("fantasy_league_invites._resolve_workspace_id", return_value=workspace_id), patch(
            "suite_workspace.get_active_workspace_id", return_value=workspace_id
        ):
            yield

    def test_save_imported_league_publishes_shared_document(self) -> None:
        session: dict = {}
        context = _seed_imported_league(session, user_id="user:donny")
        league_id = resolve_canonical_league_id(context)
        shared = load_shared_league(league_id)
        self.assertIsNotNone(shared)
        assert shared is not None
        self.assertEqual(shared.get("league_name"), "Invite Test League")
        self.assertEqual(str(shared.get("commissioner_user_id") or ""), "user:donny")
        self.assertTrue(shared.get("league_rosters"))

    def test_commissioner_invite_and_accept_links_same_league_id(self) -> None:
        self._write_registry(
            {
                "by_owner": {
                    "user:donny": {
                        "owner_user_id": "user:donny",
                        "owner_external_id": "donny",
                        "workspace_id": "daniel",
                        "label": "Daniel",
                    },
                    "user:seal11": {
                        "owner_user_id": "user:seal11",
                        "owner_external_id": "seal11",
                        "workspace_id": "ariel",
                        "label": "Ariel",
                    },
                }
            }
        )

        session_a: dict = {}
        context_a = _seed_imported_league(session_a, user_id="user:donny")
        league_id = resolve_canonical_league_id(context_a)
        assert league_id

        with _as_user("user:donny"):
            invite, err = create_league_invite(session_a, context_a, invitee_target="ariel")
        self.assertEqual(err, "")
        assert invite is not None
        self.assertEqual(invite["status"], INVITE_STATUS_PENDING)
        self.assertEqual(invite["invitee_workspace_id"], "ariel")

        shared = load_shared_league(league_id)
        assert shared is not None
        self.assertEqual(len(shared.get("league_invites") or []), 1)

        session_b: dict = {"_suite_owned_workspace_id": "ariel"}
        with _as_user("user:seal11"), self._workspace("ariel"):
            pending = list_pending_invites_for_session(session_b)
            self.assertEqual(len(pending), 1)
            entry, context_b, accept_err = join_shared_league_from_invite(
                session_b,
                league_id=league_id,
                invite_id=str(invite["invite_id"]),
                team_name="Team 2",
            )
        self.assertEqual(accept_err, "")
        assert entry is not None
        assert context_b is not None
        self.assertEqual(entry.get("draft_type"), DRAFT_TYPE_IMPORTED)
        self.assertEqual(entry.get("team_name"), "Team 2")
        self.assertEqual(resolve_canonical_league_id(context_b), league_id)

        archives = list_draft_archives(session_b)
        self.assertEqual(len(archives), 1)
        self.assertEqual(str(archives[0].get("draft_fingerprint") or ""), str(shared.get("draft_fingerprint") or ""))

        shared_after = load_shared_league(league_id)
        assert shared_after is not None
        invites = shared_after.get("league_invites") or []
        self.assertEqual(invites[0]["status"], INVITE_STATUS_ACCEPTED)
        self.assertEqual(invites[0]["claimed_team"], "Team 2")
        self.assertEqual(str((shared_after.get("team_ownership") or {}).get("Team 2", {}).get("user_id")), "user:seal11")

        with _as_user("user:donny"):
            ctx_a = get_league_context(session_a, str(context_a.get("league_context_id") or ""))
            assert ctx_a is not None
            synced = upsert_league_context(session_a, ctx_a)
            from fantasy_shared_league_store import sync_context_with_shared_store

            synced = sync_context_with_shared_store(session_a, synced)
            enabled, msg = trades_enabled(synced, session_a)
        self.assertTrue(enabled, msg)

    def test_inbox_written_for_invitee_workspace(self) -> None:
        self._write_registry(
            {
                "by_owner": {
                    "user:donny": {
                        "owner_user_id": "user:donny",
                        "owner_external_id": "donny",
                        "workspace_id": "daniel",
                    },
                    "user:seal11": {
                        "owner_user_id": "user:seal11",
                        "owner_external_id": "seal11",
                        "workspace_id": "ariel",
                    },
                }
            }
        )
        session_a: dict = {}
        context_a = _seed_imported_league(session_a, user_id="user:donny")
        with _as_user("user:donny"):
            invite, err = create_league_invite(session_a, context_a, invitee_target="ariel")
        self.assertEqual(err, "")
        assert invite is not None

        from fantasy_league_invites import _read_inbox

        inbox = _read_inbox("ariel")
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]["invite_id"], invite["invite_id"])

    def test_duplicate_pending_invite_blocked(self) -> None:
        session: dict = {}
        context = _seed_imported_league(session, user_id="user:donny")
        with _as_user("user:donny"):
            first, err1 = create_league_invite(session, context, invitee_target="ariel")
            second, err2 = create_league_invite(session, context, invitee_target="ariel")
        self.assertEqual(err1, "")
        self.assertIn("already exists", err2.lower())
        assert first is not None

    def test_stale_commissioner_id_allows_upload_owner(self) -> None:
        session: dict = {}
        context = _seed_imported_league(session, user_id="user:daniel")
        league_context_id = str(context.get("league_context_id") or "")
        loaded = get_league_context(session, league_context_id) or context
        meta = dict(loaded.get("metadata") or {})
        meta["commissioner_user_id"] = "961df5e9-cdde-48d7-80dd-95a8ba3f46e5"
        loaded["metadata"] = meta
        upsert_league_context(session, loaded)

        with _as_user("user:daniel"):
            self.assertTrue(is_league_commissioner(get_league_context(session, league_context_id), "user:daniel"))
            invite_ctx = commissioner_invite_context(session)
        self.assertIsNotNone(invite_ctx)
        assert invite_ctx is not None
        self.assertEqual(
            str((invite_ctx.get("metadata") or {}).get("commissioner_user_id") or ""),
            "user:daniel",
        )

    def test_archive_only_imported_league_gains_invite_context_after_migration(self) -> None:
        session: dict = {"_suite_cloud_user_id": "f66b85aa-1192-4f93-a669-d238bcd6858b"}
        with _as_user("f66b85aa-1192-4f93-a669-d238bcd6858b"):
            entry, _context = save_imported_league_context(
                session,
                _four_team_board(),
                my_team_name="Daniel",
                draft_name="Office League 2026",
                save_only=True,
                assign_team=True,
            )
        store = dict(session.get("fantasy_league_context_state") or {})
        store["contexts"] = {}
        session["fantasy_league_context_state"] = store

        with _as_user("f66b85aa-1192-4f93-a669-d238bcd6858b"):
            from fantasy_league_context import migrate_legacy_archives_to_contexts

            created = migrate_legacy_archives_to_contexts(session)
            self.assertGreaterEqual(created, 1)
            invite_ctx = commissioner_invite_context(session)
        self.assertIsNotNone(invite_ctx)
        assert invite_ctx is not None
        self.assertEqual(str(invite_ctx.get("context_type") or ""), "real_league")
        self.assertTrue(is_league_commissioner(invite_ctx, "f66b85aa-1192-4f93-a669-d238bcd6858b"))
        self.assertEqual(str(entry.get("draft_id") or ""), str((invite_ctx.get("metadata") or {}).get("source_draft_id") or ""))

    def test_invite_panel_trace_reports_commissioner_mismatch(self) -> None:
        session: dict = {
            "_suite_auth_session": True,
            "_suite_cloud_user_id": "f66b85aa-1192-4f93-a669-d238bcd6858b",
            "_suite_auth_user_id": "f66b85aa-1192-4f93-a669-d238bcd6858b",
            "_suite_auth_external_id": "daniel",
        }
        with _as_user("f66b85aa-1192-4f93-a669-d238bcd6858b"):
            entry, context = save_imported_league_context(
                session,
                _four_team_board(),
                my_team_name="Daniel",
                draft_name="Office League 2026",
                save_only=True,
                assign_team=True,
            )
        meta = dict(context.get("metadata") or {})
        meta["commissioner_user_id"] = "00000000-0000-0000-0000-000000000099"
        context["metadata"] = meta
        ownership = dict(context.get("team_ownership") or {})
        ownership["Daniel"] = {"user_id": "00000000-0000-0000-0000-000000000088"}
        context["team_ownership"] = ownership
        store = dict(session.get("fantasy_league_context_state") or {})
        contexts = dict(store.get("contexts") or {})
        league_context_id = str(context.get("league_context_id") or "").strip()
        contexts[league_context_id] = context
        store["contexts"] = contexts
        session["fantasy_league_context_state"] = store

        with _as_user("f66b85aa-1192-4f93-a669-d238bcd6858b"):
            trace = build_commissioner_invite_panel_trace(session)
        self.assertGreaterEqual(int(trace.get("uploaded_league_session_count") or 0), 1)
        self.assertFalse(trace.get("commissioner_invite_context_found"))
        leagues = trace.get("uploaded_leagues") or []
        self.assertGreaterEqual(len(leagues), 1)
        row = next(item for item in leagues if str(item.get("draft_id")) == str(entry.get("draft_id")))
        self.assertTrue(row.get("context_exists"))
        self.assertIn("does not match", str(row.get("block_reason") or "").lower())
        self.assertIn("None", str(trace.get("commissioner_invite_context_reason") or ""))

    def test_invite_panel_trace_detects_snapshot_only_team_count(self) -> None:
        session: dict = {
            "_suite_auth_session": True,
            "_suite_cloud_user_id": "f66b85aa-1192-4f93-a669-d238bcd6858b",
            "_suite_auth_user_id": "f66b85aa-1192-4f93-a669-d238bcd6858b",
            "_suite_auth_external_id": "daniel",
        }
        with _as_user("f66b85aa-1192-4f93-a669-d238bcd6858b"):
            entry, _context = save_imported_league_context(
                session,
                _four_team_board(),
                my_team_name="Daniel",
                draft_name="Snapshot League",
                save_only=True,
                assign_team=True,
            )
        entry = dict(entry)
        entry["league_rosters"] = {}
        entry["snapshot"] = {"team_count": 4, "my_team_player_count": 3}
        archives = [
            {**row, "league_rosters": {}, "snapshot": entry["snapshot"]}
            if str(row.get("draft_id")) == str(entry.get("draft_id"))
            else row
            for row in list_draft_archives(session)
        ]
        session[DRAFT_ARCHIVE_KEY] = archives

        with _as_user("f66b85aa-1192-4f93-a669-d238bcd6858b"):
            trace = build_commissioner_invite_panel_trace(session)
        self.assertGreaterEqual(int(trace.get("uploaded_league_session_count") or 0), 1)
        row = next(item for item in (trace.get("uploaded_leagues") or []) if str(item.get("draft_id")) == str(entry.get("draft_id")))
        self.assertEqual(int(row.get("team_count_hint") or 0), 4)

    def test_invite_joiner_is_not_commissioner(self) -> None:
        session: dict = {}
        context = _seed_imported_league(session, user_id="user:donny")
        league_context_id = str(context.get("league_context_id") or "")
        loaded = get_league_context(session, league_context_id) or context
        loaded = assign_team_owner_to_context(
            loaded,
            "Team 2",
            user_id="user:seal11",
            email="seal11@test",
            display_name="Seal11",
        )
        loaded["my_team_name"] = "Team 2"
        meta = dict(loaded.get("metadata") or {})
        meta["joined_via_invite"] = True
        meta["commissioner_user_id"] = "user:donny"
        loaded["metadata"] = meta
        upsert_league_context(session, loaded)

        with _as_user("user:seal11"):
            self.assertFalse(is_league_commissioner(get_league_context(session, league_context_id), "user:seal11"))
            self.assertIsNone(commissioner_invite_context(session))


if __name__ == "__main__":
    unittest.main()
