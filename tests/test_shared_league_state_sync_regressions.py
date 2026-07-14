"""Regressions: ownership, Active League persistence, invite origin, stale Team X header."""

from __future__ import annotations

import unittest
from unittest.mock import patch


class OwnershipMergeTests(unittest.TestCase):
    def test_pull_prefers_shared_firm_over_newer_local(self) -> None:
        from fantasy_shared_league_store import _merge_team_ownership

        local = {
            "Team Y": {
                "user_id": "user:daniel",
                "display_name": "Daniel Cohen11",
                "assigned_at": "2026-07-14T20:00:00+00:00",
                "claim_status": "claimed",
            }
        }
        shared = {
            "Team Y": {
                "user_id": "user:coakley11",
                "display_name": "coakley11",
                "assigned_at": "2026-07-14T19:00:00+00:00",
                "claim_status": "claimed",
            }
        }
        merged = _merge_team_ownership(local, shared, prefer_firm_from="last")
        self.assertEqual(merged["Team Y"]["user_id"], "user:coakley11")

    def test_push_keeps_shared_firm_against_local_overwrite(self) -> None:
        from fantasy_shared_league_store import _merge_team_ownership

        shared_existing = {
            "Team Y": {
                "user_id": "user:coakley11",
                "display_name": "coakley11",
                "assigned_at": "2026-07-14T19:00:00+00:00",
                "claim_status": "claimed",
            }
        }
        local = {
            "Team Y": {
                "user_id": "user:daniel",
                "display_name": "Daniel Cohen11",
                "assigned_at": "2026-07-14T21:00:00+00:00",
                "claim_status": "claimed",
            }
        }
        merged = _merge_team_ownership(shared_existing, local, prefer_firm_from="first")
        self.assertEqual(merged["Team Y"]["user_id"], "user:coakley11")


class StaleTeamHeaderTests(unittest.TestCase):
    def test_active_draft_ignores_leftover_team_x(self) -> None:
        from fantasy_league_context import (
            CONTEXT_TYPE_REAL_LEAGUE,
            ensure_fantasy_league_context_state,
            upsert_league_context,
        )
        from global_fantasy_settings_state import get_active_fantasy_team

        session: dict = {
            "active_draft_archive_id": "fresh10",
            "room_your_team": "Team X",
            "live_draft_my_team": "Team X",
            "draft_archive_teams": [
                {
                    "draft_id": "fresh10",
                    "draft_name": "Fresh 10-Pick Live Test",
                    "team_name": "Team 1",
                    "league_context_id": "ctx:fresh10",
                }
            ],
        }
        ensure_fantasy_league_context_state(session)
        upsert_league_context(
            session,
            {
                "league_context_id": "ctx:fresh10",
                "context_type": CONTEXT_TYPE_REAL_LEAGUE,
                "display_name": "Fresh 10-Pick Live Test",
                "my_team_name": "Team 1",
                "league_rosters": {"Team 1": {"players": []}, "Team 2": {"players": []}},
            },
        )
        store = ensure_fantasy_league_context_state(session)
        store["active_league_context_id"] = "ctx:fresh10"

        with patch(
            "global_fantasy_settings_state.active_fantasy_team_source",
            return_value="active_draft",
        ), patch(
            "draft_room_context.is_multiplayer_draft_active",
            return_value=False,
        ):
            self.assertEqual(get_active_fantasy_team(session), "Team 1")
            self.assertEqual(session.get("room_your_team"), "Team 1")


class MembershipPreservesActiveTests(unittest.TestCase):
    def test_finalize_does_not_flip_existing_active(self) -> None:
        from fantasy_shared_league_startup_sync import finalize_repaired_archives_for_membership

        session: dict = {"active_draft_archive_id": "keep_me"}
        shared = {"league_id": "lg1", "draft_id": "other_draft"}
        with patch(
            "fantasy_admin_draft_archive_repair.find_league_context_by_league_id",
            return_value={
                "league_context_id": "ctx:other",
                "metadata": {"source_draft_id": "other_draft"},
                "my_team_name": "Team A",
            },
        ), patch(
            "fantasy_shared_league_startup_sync.apply_workspace_member_identity_from_shared",
            side_effect=lambda sess, ctx, doc: ctx,
        ), patch(
            "fantasy_league_context.upsert_league_context"
        ), patch(
            "fantasy_league_context.repair_missing_draft_archives_from_contexts",
            return_value=0,
        ), patch(
            "fantasy_admin_draft_archive_repair._normalize_repaired_archive_types",
            return_value=0,
        ), patch(
            "fantasy_admin_draft_archive_repair._sync_archives_to_workspace_team",
            return_value=0,
        ), patch(
            "workflow_persist_guard.restore_active_draft_archive_selection"
        ) as restore:
            trace = finalize_repaired_archives_for_membership(session, shared_doc=shared)
        restore.assert_not_called()
        self.assertEqual(session.get("active_draft_archive_id"), "keep_me")
        self.assertEqual(trace["active_restore_trace"].get("skipped"), "preserve_existing_session_active")


class InviteOriginTests(unittest.TestCase):
    def test_live_shared_league_keeps_live_draft_type_on_accept(self) -> None:
        from draft_archive_state import DRAFT_TYPE_LIVE
        from fantasy_league_invites import join_shared_league_from_invite

        session: dict = {"draft_archive_teams": [], "draft_shared_settings": {}}
        shared = {
            "league_id": "lg-live",
            "league_name": "Robins Fantasy",
            "created_from": "live_draft",
            "source": "live_draft_room",
            "source_draft_type": "live_draft_room",
            "source_room_code": "ABC123",
            "league_rosters": {"Team X": {"players": []}, "Team Y": {"players": []}},
            "team_ownership": {
                "Team X": {"user_id": "user:daniel", "claim_status": "claimed"},
                "Team Y": {"provisional": True, "claim_status": "reserved"},
            },
            "league_invites": [
                {
                    "invite_id": "inv1",
                    "status": "pending",
                    "league_id": "lg-live",
                    "league_name": "Robins Fantasy",
                    "invitee_user_id": "user:coakley11",
                    "invitee_workspace_id": "coakley11",
                }
            ],
            "revision": 3,
        }

        with patch("fantasy_league_invites._resolve_user_id", return_value="user:coakley11"), patch(
            "fantasy_league_invites._resolve_external_id", return_value="coakley11"
        ), patch(
            "fantasy_league_invites._resolve_workspace_id", return_value="coakley11"
        ), patch(
            "fantasy_league_invites.load_shared_league", return_value=shared
        ), patch(
            "fantasy_league_invites._invite_matches_user", return_value=True
        ), patch(
            "fantasy_league_context.resolve_canonical_save_ids",
            return_value=("draft_live_1", "ctx:draft_live_1", "fp1"),
        ), patch(
            "fantasy_shared_league_store.save_shared_league", return_value=shared
        ), patch(
            "fantasy_league_invites.remove_invite_from_inbox"
        ), patch(
            "fantasy_league_invites.sync_context_with_shared_store",
            side_effect=lambda sess, ctx: ctx,
        ):
            entry, context, err = join_shared_league_from_invite(
                session,
                league_id="lg-live",
                invite_id="inv1",
                team_name="Team Y",
            )
        self.assertEqual(err, "")
        self.assertIsNotNone(entry)
        self.assertEqual(str(entry.get("draft_type") or ""), DRAFT_TYPE_LIVE)
        meta = (context or {}).get("metadata") if isinstance(context, dict) else {}
        self.assertEqual(str((meta or {}).get("created_from") or ""), "live_draft")


if __name__ == "__main__":
    unittest.main()
