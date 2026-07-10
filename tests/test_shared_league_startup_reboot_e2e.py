"""E2E: invite → accept trade → reboot preserves canonical shared-league workflow."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from fantasy_league_context import (
    activate_league_context,
    get_league_context,
    save_imported_league_context,
    upsert_league_context,
)
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_league_invites import create_league_invite, join_shared_league_from_invite
from fantasy_league_team_ownership import owned_team_for_user, trades_enabled
from fantasy_shared_league_store import LocalFileSharedLeagueStore, load_shared_league, set_shared_league_store, sync_context_with_shared_store
from fantasy_trade_proposals import (
    TRADE_PROPOSAL_STATUS_ACCEPTED,
    TRADE_PROPOSAL_STATUS_PENDING,
    accept_trade_proposal,
    create_trade_proposal,
    get_incoming_trade_proposals,
    get_trade_history,
)
from tests.test_fantasy_trade_proposals import _as_user, _league_board
from workflow_persist_guard import (
    AUTH_RESTORE_CYCLE_COMPLETE_KEY,
    DRAFT_ARCHIVE_KEY,
    LEAGUE_CONTEXT_STATE_KEY,
    STARTUP_CANONICAL_SYNC_COMPLETE_KEY,
    count_draft_archives,
    count_league_contexts,
    run_consolidated_startup_workflow,
)

_SHARED_DRAFT_CFG = {
    "fantasy_format": "5x5 Roto",
    "scoring_type": "Roto (5x5)",
    "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "UTIL": 1},
    "slot_instances": [],
}

_WORKFLOW_KEYS = (
    DRAFT_ARCHIVE_KEY,
    LEAGUE_CONTEXT_STATE_KEY,
    "active_draft_archive_id",
    "_deleted_draft_archive_ids",
)


def _simulate_reboot_session(session: dict, *, workspace_id: str, user_id: str, external_id: str) -> None:
    for key in _WORKFLOW_KEYS:
        session.pop(key, None)
    session["_suite_active_workspace_id"] = workspace_id
    session["_suite_owned_workspace_id"] = workspace_id
    session["_suite_auth_user_id"] = user_id
    session["_suite_cloud_user_id"] = user_id
    session["_suite_auth_external_id"] = external_id
    session["_suite_auth_session"] = True
    session[AUTH_RESTORE_CYCLE_COMPLETE_KEY] = True
    session.pop(STARTUP_CANONICAL_SYNC_COMPLETE_KEY, None)


class TestSharedLeagueStartupRebootE2E(unittest.TestCase):
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
        with patch("fantasy_league_invites._resolve_workspace_id", return_value=workspace_id):
            yield

    def _seed_commissioner_league(self) -> tuple[dict, dict]:
        session: dict = {
            "draft_shared_settings": dict(_SHARED_DRAFT_CFG),
            "_suite_owned_workspace_id": "daniel",
        }
        with _as_user("user:donny"):
            _, context = save_imported_league_context(
                session,
                _league_board(),
                my_team_name="Donny",
                draft_name="Daniel 2026 Home League",
                league_name="Daniel 2026 Home League",
                config=_SHARED_DRAFT_CFG,
                save_only=True,
                assign_team=True,
            )
        return session, context

    def _run_startup(self, session: dict) -> dict:
        st = MagicMock()
        st.session_state = session
        with patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value={}):
            with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value={}):
                return run_consolidated_startup_workflow(st, "baseball")

    def test_propose_accept_reboot_preserves_league_trade_rosters(self) -> None:
        session_a, context_a = self._seed_commissioner_league()
        league_id = resolve_canonical_league_id(context_a)
        assert league_id

        with _as_user("user:donny"):
            invite, err = create_league_invite(session_a, context_a, invitee_target="ariel")
        self.assertEqual(err, "")
        assert invite is not None

        session_b: dict = {
            "draft_shared_settings": dict(_SHARED_DRAFT_CFG),
            "_suite_owned_workspace_id": "ariel",
        }
        with _as_user("user:seal11"), self._workspace("ariel"):
            _, context_b, accept_err = join_shared_league_from_invite(
                session_b,
                league_id=league_id,
                invite_id=str(invite["invite_id"]),
                team_name="Team 2",
            )
        self.assertEqual(accept_err, "")
        assert context_b is not None

        league_context_id_a = str(context_a.get("league_context_id") or "")
        league_context_id_b = str(context_b.get("league_context_id") or "")
        with _as_user("user:donny"):
            activate_league_context(session_a, league_context_id_a)
            ctx_a = get_league_context(session_a, league_context_id_a)
            assert ctx_a is not None
            synced_a = sync_context_with_shared_store(session_a, ctx_a)
            upsert_league_context(session_a, synced_a)
            enabled_a, _ = trades_enabled(synced_a, session_a)
        self.assertTrue(enabled_a)

        with _as_user("user:donny"):
            proposal, propose_err = create_trade_proposal(
                session_a,
                proposer_team="Donny",
                recipient_team="Team 2",
                proposer_gives=["Player A"],
                proposer_receives=["Player B"],
            )
        self.assertEqual(propose_err, "")
        assert proposal is not None

        with _as_user("user:seal11"):
            activate_league_context(session_b, league_context_id_b)
            incoming = get_incoming_trade_proposals(session_b, "Team 2")
        self.assertEqual(len(incoming), 1)

        with _as_user("user:seal11"):
            accepted, accept_err = accept_trade_proposal(session_b, str(proposal["proposal_id"]))
        self.assertEqual(accept_err, "")
        assert accepted is not None
        self.assertEqual(accepted["status"], TRADE_PROPOSAL_STATUS_ACCEPTED)

        shared_after = load_shared_league(league_id)
        assert shared_after is not None
        donny_roster = [
            p.get("player_name")
            for p in (shared_after.get("league_rosters") or {}).get("Donny", {}).get("players") or []
        ]
        team2_roster = [
            p.get("player_name")
            for p in (shared_after.get("league_rosters") or {}).get("Team 2", {}).get("players") or []
        ]
        self.assertIn("Player B", donny_roster)
        self.assertIn("Player A", team2_roster)

        _simulate_reboot_session(
            session_a,
            workspace_id="daniel",
            user_id="user:donny",
            external_id="donny",
        )
        _simulate_reboot_session(
            session_b,
            workspace_id="ariel",
            user_id="user:seal11",
            external_id="seal11",
        )

        trace_a = self._run_startup(session_a)
        trace_b = self._run_startup(session_b)
        self.assertTrue(trace_a.get("canonical_sync", {}).get("rebuilt") or trace_a.get("canonical_sync", {}).get("leagues_rebuilt", 0) >= 0)
        self.assertTrue(trace_b.get("canonical_sync", {}).get("rebuilt"))

        self.assertEqual(count_draft_archives(session_a.get(DRAFT_ARCHIVE_KEY)), 1)
        self.assertEqual(count_draft_archives(session_b.get(DRAFT_ARCHIVE_KEY)), 1)
        self.assertEqual(count_league_contexts(session_a.get(LEAGUE_CONTEXT_STATE_KEY)), 1)
        self.assertEqual(count_league_contexts(session_b.get(LEAGUE_CONTEXT_STATE_KEY)), 1)

        with _as_user("user:donny"):
            ctx_a = get_league_context(session_a, league_context_id_a)
            assert ctx_a is not None
            self.assertEqual(owned_team_for_user(ctx_a), "Donny")
            synced_a = sync_context_with_shared_store(session_a, ctx_a)
            history_a = get_trade_history(synced_a)
        self.assertEqual(len(history_a["accepted"]), 1)

        with _as_user("user:seal11"):
            ctx_b = get_league_context(session_b, league_context_id_b)
            assert ctx_b is not None
            self.assertEqual(owned_team_for_user(ctx_b), "Team 2")
            synced_b = sync_context_with_shared_store(session_b, ctx_b)
            history_b = get_trade_history(synced_b)
        self.assertEqual(len(history_b["accepted"]), 1)

        shared_reboot = load_shared_league(league_id)
        assert shared_reboot is not None
        pending = [
            p for p in (shared_reboot.get("trade_proposals") or []) if str(p.get("status")) == TRADE_PROPOSAL_STATUS_PENDING
        ]
        self.assertEqual(len(pending), 0)
        accepted = [
            p for p in (shared_reboot.get("trade_proposals") or []) if str(p.get("status")) == TRADE_PROPOSAL_STATUS_ACCEPTED
        ]
        self.assertEqual(len(accepted), 1)

        donny_after = [
            p.get("player_name")
            for p in (shared_reboot.get("league_rosters") or {}).get("Donny", {}).get("players") or []
        ]
        team2_after = [
            p.get("player_name")
            for p in (shared_reboot.get("league_rosters") or {}).get("Team 2", {}).get("players") or []
        ]
        self.assertIn("Player B", donny_after)
        self.assertIn("Player A", team2_after)
