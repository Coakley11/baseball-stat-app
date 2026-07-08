"""Headless two-account smoke: invite → claim → trade cross-account persistence."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fantasy_league_context import activate_league_context, get_league_context, save_imported_league_context, upsert_league_context
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_league_invites import create_league_invite, join_shared_league_from_invite, list_pending_invites_for_session
from fantasy_league_team_ownership import owned_team_for_user, trades_enabled
from fantasy_shared_league_store import LocalFileSharedLeagueStore, load_shared_league, set_shared_league_store, sync_context_with_shared_store
from fantasy_trade_proposals import (
    TRADE_PROPOSAL_STATUS_ACCEPTED,
    accept_trade_proposal,
    create_trade_proposal,
    get_incoming_trade_proposals,
    get_trade_history,
)
from tests.test_fantasy_trade_proposals import _as_user, _league_board

_SHARED_DRAFT_CFG = {
    "fantasy_format": "5x5 Roto",
    "scoring_type": "Roto (5x5)",
    "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "UTIL": 1},
    "slot_instances": [],
}


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def _ok(label: str) -> None:
    print(f"PASS: {label}")


def _write_registry(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    print("Shared league invite + trade two-account smoke (headless)")
    tmp = tempfile.TemporaryDirectory()
    store_root = Path(tmp.name) / "shared"
    workspace_root = Path(tmp.name) / "workspaces"
    store_root.mkdir(parents=True)
    workspace_root.mkdir(parents=True)
    set_shared_league_store(LocalFileSharedLeagueStore(root=store_root))

    def _test_workspace_dir(workspace_id: str | None = None) -> Path:
        from suite_workspace import normalize_workspace_id

        ws = normalize_workspace_id(workspace_id)
        path = workspace_root / ws
        path.mkdir(parents=True, exist_ok=True)
        return path

    registry_path = ROOT / "data" / "workspaces" / "_ownership_registry.json"
    registry_backup = registry_path.read_text(encoding="utf-8") if registry_path.is_file() else None
    _write_registry(
        registry_path,
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
        },
    )

    try:
        with patch("suite_workspace.workspace_dir", side_effect=_test_workspace_dir), patch(
            "fantasy_league_invites._resolve_workspace_id",
            side_effect=lambda session=None: str((session or {}).get("_suite_owned_workspace_id") or ""),
        ):
            session_a: dict = {
                "draft_shared_settings": dict(_SHARED_DRAFT_CFG),
                "_suite_owned_workspace_id": "daniel",
            }
            with _as_user("user:donny"):
                _, context_a = save_imported_league_context(
                    session_a,
                    _league_board(),
                    my_team_name="Donny",
                    draft_name="Daniel 2026 Home League",
                    league_name="Daniel 2026 Home League",
                    config=_SHARED_DRAFT_CFG,
                    save_only=True,
                    assign_team=True,
                )
            league_id = resolve_canonical_league_id(context_a)
            if not league_id:
                _fail("commissioner league_id missing after import save")
            _ok("1. Daniel imports/saves uploaded league and publishes shared document")

            with _as_user("user:donny"):
                invite, err = create_league_invite(session_a, context_a, invitee_target="ariel")
            if err or not invite:
                _fail(f"invite failed: {err}")
            _ok("2. Daniel invites ariel workspace")

            session_b: dict = {
                "draft_shared_settings": dict(_SHARED_DRAFT_CFG),
                "_suite_owned_workspace_id": "ariel",
            }
            with _as_user("user:seal11"):
                pending = list_pending_invites_for_session(session_b)
                if len(pending) != 1:
                    _fail(f"invitee pending invites expected 1, got {len(pending)}")
            _ok("3. Invitee sees pending invite in inbox")

            with _as_user("user:seal11"):
                entry, context_b, accept_err = join_shared_league_from_invite(
                    session_b,
                    league_id=league_id,
                    invite_id=str(invite["invite_id"]),
                    team_name="Team 2",
                )
            if accept_err or not entry or not context_b:
                _fail(f"invite accept failed: {accept_err}")
            if resolve_canonical_league_id(context_b) != league_id:
                _fail("invitee library entry league_id mismatch")
            _ok("4. Invitee claims Team 2 and links library entry to same league_id")

            with _as_user("user:donny"):
                if owned_team_for_user(context_a) != "Donny":
                    _fail("Daniel team claim missing")
            with _as_user("user:seal11"):
                if owned_team_for_user(context_b) != "Team 2":
                    _fail("Invitee team claim missing")
            _ok("5. Both accounts own different claimed teams")

            league_context_id_a = str(context_a.get("league_context_id") or "")
            league_context_id_b = str(context_b.get("league_context_id") or "")
            with _as_user("user:donny"):
                activate_league_context(session_a, league_context_id_a)
                synced_a = sync_context_with_shared_store(session_a, get_league_context(session_a, league_context_id_a) or context_a)
                upsert_league_context(session_a, synced_a)
                activate_league_context(session_a, league_context_id_a)
                enabled_a, msg_a = trades_enabled(synced_a, session_a)
            if not enabled_a:
                _fail(f"trades not enabled for Daniel: {msg_a}")

            with _as_user("user:seal11"):
                activate_league_context(session_b, league_context_id_b)
                synced_b = sync_context_with_shared_store(session_b, get_league_context(session_b, league_context_id_b) or context_b)
                upsert_league_context(session_b, synced_b)
                activate_league_context(session_b, league_context_id_b)
                enabled_b, msg_b = trades_enabled(synced_b, session_b)
            if not enabled_b:
                _fail(f"trades not enabled for invitee: {msg_b}")
            _ok("6. Trades unlock for both accounts after two distinct owner_user_ids")

            with _as_user("user:donny"):
                proposal, propose_err = create_trade_proposal(
                    session_a,
                    proposer_team="Donny",
                    recipient_team="Team 2",
                    proposer_gives=["Player A"],
                    proposer_receives=["Player B"],
                )
            if propose_err or not proposal:
                _fail(f"propose failed: {propose_err}")
            shared = load_shared_league(league_id)
            if not shared or len(shared.get("trade_proposals") or []) != 1:
                _fail("shared store missing pending proposal")
            _ok("7. Proposed trade persists to shared store")

            with _as_user("user:seal11"):
                stale = get_league_context(session_b, league_context_id_b) or {}
                stale.setdefault("workflow", {})["trade_proposals"] = []
                synced = sync_context_with_shared_store(session_b, stale)
                upsert_league_context(session_b, synced)
                activate_league_context(session_b, league_context_id_b)
                incoming = get_incoming_trade_proposals(session_b, "Team 2")
            if len(incoming) != 1:
                _fail(f"invitee reload did not see pending trade: {len(incoming)}")
            _ok("8. Receiving account sees pending trade after reload/sync")

            with _as_user("user:seal11"):
                accepted, accept_err = accept_trade_proposal(session_b, str(proposal["proposal_id"]))
            if accept_err or not accepted:
                _fail(f"accept failed: {accept_err}")
            shared_after = load_shared_league(league_id)
            if not shared_after:
                _fail("shared store missing after accept")
            donny_players = [
                p.get("player_name")
                for p in (shared_after.get("league_rosters") or {}).get("Donny", {}).get("players") or []
            ]
            team2_players = [
                p.get("player_name")
                for p in (shared_after.get("league_rosters") or {}).get("Team 2", {}).get("players") or []
            ]
            if "Player B" not in donny_players or "Player A" not in team2_players:
                _fail(f"canonical roster swap missing: Donny={donny_players}, Team2={team2_players}")
            if not shared_after.get("league_activity"):
                _fail("shared league_activity missing after accept")
            _ok("9. Accept swaps rosters in canonical shared document + records activity")

            with _as_user("user:donny"):
                ctx_a = get_league_context(session_a, league_context_id_a) or {}
                synced_a = sync_context_with_shared_store(session_a, ctx_a)
                history_a = get_trade_history(synced_a)
            with _as_user("user:seal11"):
                ctx_b = get_league_context(session_b, league_context_id_b) or {}
                synced_b = sync_context_with_shared_store(session_b, ctx_b)
                history_b = get_trade_history(synced_b)
            if len(history_a.get("accepted") or []) != 1 or len(history_b.get("accepted") or []) != 1:
                _fail("trade history not visible on both accounts")
            if not history_a.get("activity") or not history_b.get("activity"):
                _fail("league activity timeline not visible on both accounts")
            if history_a["accepted"][0].get("league_id") != league_id:
                _fail("trade history league_id missing on commissioner side")
            _ok("10. Trade history tied to league_id visible to both accounts after reload")

    finally:
        set_shared_league_store(None)
        if registry_backup is not None:
            registry_path.write_text(registry_backup, encoding="utf-8")
        elif registry_path.is_file():
            registry_path.unlink()
        tmp.cleanup()

    print("ALL PASS — shared league invite + trade smoke complete")


if __name__ == "__main__":
    main()
