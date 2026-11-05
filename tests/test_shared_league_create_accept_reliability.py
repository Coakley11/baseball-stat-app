"""Shared League creation and invite acceptance report only what was actually saved (2026-11-05).

The Danny-Barry case with sanitized ids: a completed two-team Live Draft (made by the real pick
engine), Danny creates "Danny vs Barry League", invites user_coakley11 (Barry), Barry accepts and
claims team Barry. Sign-in on, with Auth and suite ids that differ, as hosted.

Covered:
- creation reports a refused or failed shared write instead of claiming success, and the kept
  success message appears only when the shared write and the cloud save are both confirmed;
- the league is published as a Live Draft (also without a room code), so an invitee's copy is a
  Live Draft, not an Imported League;
- creating a league does not replace the account's active league; accepting does not either;
- an acceptance the shared league does not record is undone locally and reported;
- a Library copy recovered from the Shared Draft room is left untouched by accepting;
- the invite panel offers every league the commissioner runs, the new one first.
"""

from __future__ import annotations

import copy
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

import tests.test_invite_discovery_hosted_ids as hosted
from draft_archive_state import DRAFT_TYPE_LIVE, get_draft_archive, list_draft_archives
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_league_invites import commissioner_invite_contexts, create_league_invite, preview_league_invitee
from fantasy_shared_league_store import invalidate_shared_league_doc_cache, load_shared_league
from live_draft_pick_engine import live_draft_make_pick
from live_draft_shared_league import save_live_draft_shared_league_context

DANNY, BARRY = hosted.DANNY, hosted.BARRY
PICKS = [(1, "Danny", "olsonma02", "Matt Olson", "1B"), (2, "Barry", "raleica01", "Cal Raleigh", "C"),
         (3, "Barry", "alonspe01", "Pete Alonso", "1B"), (4, "Danny", "perezsa02", "Salvador Perez", "C")]
SEATS = {"Danny": {"user_id": DANNY["suite"], "display_name": "Danny"},
         "Barry": {"user_id": BARRY["auth"], "email": "coakley11@example.org", "display_name": "Barry"}}


def completed_room() -> dict:
    pool = pd.DataFrame([{"playerID": pid, "fullName": name, "Primary Position": pos, "Team": "ATL",
                          "Eligible Positions": pos, "Expected Fantasy Value": 80.0 - n, "Model Rank": n,
                          "Market Rank": n, "Fantasy Edge": 0.0} for n, _t, pid, name, pos in PICKS])
    room = {"status": "in_progress", "current_pick_index": 0, "teams": ["Danny", "Barry"],
            "config": {"league_name": "Danny vs Barry League", "fantasy_format": "5x5 Roto", "scoring_type": "5x5 Roto",
                       "num_teams": 2, "picks_per_team": 2, "slots": {"C": 1, "1B": 1}, "teams": ["Danny", "Barry"],
                       "timer_seconds": 60},
            "pick_order": [{"Pick": n, "Round": (n + 1) // 2, "Team": t} for n, t, *_ in PICKS],
            "draft_board": [], "rosters": {"Danny": [], "Barry": []}, "drafted_player_ids": [], "pool": pool}
    for _n, _t, pid, *_ in PICKS:
        ok, msg = live_draft_make_pick(room, pool[pool["playerID"] == pid].iloc[0].to_dict(), "Manual pick",
                                       enrich_pick_context=False)
        assert ok, msg
    return room


class _Case(hosted._Case):
    def create(self, danny: dict, **kw) -> tuple[dict, dict, str]:
        with self.on(), self.as_account(DANNY):
            entry, ctx = save_live_draft_shared_league_context(
                danny, completed_room(), my_team_name="Danny", league_name="Danny vs Barry League",
                defer_activation=True, assign_team=True, preassign_owners=SEATS, **kw)
        return entry, ctx, resolve_canonical_league_id(ctx)

    def invite_barry(self, danny: dict, ctx: dict) -> dict:
        with self.on(), self.as_account(DANNY):
            found = preview_league_invitee(danny, ctx, "user_coakley11")
            invite, err = create_league_invite(danny, ctx, invitee_target="user_coakley11",
                                               confirmed_invitee_user_id=found["invitee_user_id"])
        self.assertEqual(err, "")
        return invite

    def doc(self, league_id: str) -> dict:
        invalidate_shared_league_doc_cache()
        with self.on():
            return load_shared_league(league_id) or {}

    def setUp(self) -> None:
        super().setUp()
        self._write_registry({"by_owner": {}})


class CreateTests(_Case):
    def test_the_league_is_published_as_a_live_draft_with_danny_claimed_and_barry_reserved(self) -> None:
        entry, _ctx, league_id = self.create(hosted._signed_in(DANNY))
        self.assertTrue(entry["shared_league_created"])
        self.assertEqual(entry["draft_type"], DRAFT_TYPE_LIVE)
        doc = self.doc(league_id)
        self.assertEqual((doc.get("created_from"), doc.get("source")), ("live_draft", "live_draft_room"))
        own = doc["team_ownership"]
        self.assertEqual((own["Danny"]["user_id"], own["Danny"].get("claim_status")), (DANNY["suite"], "claimed"))
        self.assertEqual(own["Barry"]["user_id"], "")  # reserved, not claimed, until Barry accepts

    def test_a_refused_shared_write_is_reported_not_called_success(self) -> None:
        from fantasy_shared_league_authz import SharedLeagueWriteRefused

        with patch("fantasy_shared_league_store.push_league_context_to_shared",
                   side_effect=SharedLeagueWriteRefused("refused")):
            entry, _ctx, _league_id = self.create(hosted._signed_in(DANNY))
        self.assertFalse(entry["shared_league_created"])
        self.assertIn("refused", entry["shared_league_push_error"])

    def test_creating_a_league_keeps_the_current_active_league(self) -> None:
        danny = hosted._signed_in(DANNY)
        danny["active_draft_archive_id"] = "my-fantasy-league"
        danny["fantasy_league_context_state"] = {"contexts": {}, "active_league_context_id": "ctx-my-fantasy-league"}
        entry, _ctx, _league_id = self.create(danny, keep_current_active=True)
        self.assertTrue(entry["activation_skipped"])
        self.assertEqual(danny["active_draft_archive_id"], "my-fantasy-league")
        self.assertEqual(danny["fantasy_league_context_state"]["active_league_context_id"], "ctx-my-fantasy-league")
        self.assertNotIn("_pending_active_league_context_id", danny)

    def test_with_no_active_league_the_new_league_becomes_active(self) -> None:
        danny = hosted._signed_in(DANNY)
        entry, ctx, _league_id = self.create(danny, keep_current_active=True)
        self.assertFalse(entry["activation_skipped"])
        self.assertEqual(danny.get("_pending_active_league_context_id"), ctx["league_context_id"])


class CreateMessageTests(unittest.TestCase):
    """The message kept for the next screen after Create Shared League."""

    def finalize(self, *, shared_push_ok: bool, readback: dict) -> dict:
        from draft_archive_ui import _finalize_shared_league_creation_success

        session: dict = {}
        _finalize_shared_league_creation_success(
            MagicMock(), session, request_id="r1", draft_id="d1", context_id="c1", canonical_id="league:1",
            my_team="Danny", preview={"league_name": "Danny vs Barry League"}, entry={}, readback=readback,
            save_call_count=1, shared_push_ok=shared_push_ok)
        return session["_live_draft_shared_league_flash"]

    def test_success_only_when_both_saves_are_confirmed(self) -> None:
        flash = self.finalize(shared_push_ok=True, readback={"cloud_enabled": True, "cloud_readback_found": True})
        self.assertEqual(flash["level"], "success")
        self.assertIn("Danny vs Barry League", flash["message"])
        self.assertEqual(self.finalize(shared_push_ok=True, readback={"cloud_readback_skipped": True})["level"],
                         "success")  # cloud saving off (local install)

    def test_a_failed_shared_write_keeps_a_warning_not_success(self) -> None:
        from ui_user_copy import SHARED_LEAGUE_LOCAL_ONLY

        flash = self.finalize(shared_push_ok=False, readback={"cloud_enabled": True, "cloud_readback_found": True})
        self.assertEqual((flash["level"], flash["message"]), ("warning", SHARED_LEAGUE_LOCAL_ONLY))

    def test_an_unconfirmed_cloud_save_keeps_a_warning_not_success(self) -> None:
        from ui_user_copy import SHARED_LEAGUE_BACKUP_UNCONFIRMED

        flash = self.finalize(shared_push_ok=True, readback={"cloud_enabled": True, "cloud_unavailable": True,
                                                              "cloud_readback_found": False})
        self.assertEqual((flash["level"], flash["message"]), ("warning", SHARED_LEAGUE_BACKUP_UNCONFIRMED))


class AcceptTests(_Case):
    def test_barry_accepts_claims_team_barry_as_a_live_draft_and_nothing_else_moves(self) -> None:
        danny = hosted._signed_in(DANNY)
        danny["active_draft_archive_id"] = "my-fantasy-league"
        _entry, ctx, league_id = self.create(danny, keep_current_active=True)
        invite = self.invite_barry(danny, ctx)
        danny_keys = ("active_draft_archive_id", "draft_archive_teams", "fantasy_league_context_state")
        danny_before = copy.deepcopy({k: danny.get(k) for k in danny_keys})
        barry = hosted._signed_in(BARRY)
        barry["active_draft_archive_id"] = "barry-own-draft"
        entry, bctx, err = self.accept(barry, BARRY, league_id, invite["invite_id"], "Barry")
        self.assertEqual(err, "")
        self.assertEqual(entry["draft_type"], DRAFT_TYPE_LIVE)              # a Live Draft for Barry too
        self.assertEqual(bctx["my_team_name"], "Barry")
        self.assertEqual(barry["active_draft_archive_id"], "barry-own-draft")  # his active draft unchanged
        self.assertEqual({k: danny.get(k) for k in danny_keys}, danny_before)  # Danny's state untouched
        doc = self.doc(league_id)
        self.assertEqual(doc["team_ownership"]["Barry"]["user_id"], BARRY["suite"])
        self.assertEqual(doc["team_ownership"]["Danny"]["user_id"], DANNY["suite"])
        stored = next(i for i in doc["league_invites"] if i["invite_id"] == invite["invite_id"])
        self.assertEqual((stored["status"], stored["claimed_team"]), ("accepted", "Barry"))

    def test_an_acceptance_the_shared_league_does_not_record_is_undone(self) -> None:
        danny = hosted._signed_in(DANNY)
        _entry, ctx, league_id = self.create(danny)
        invite = self.invite_barry(danny, ctx)
        barry = hosted._signed_in(BARRY)
        before = copy.deepcopy({k: barry.get(k) for k in ("draft_archive_teams", "fantasy_league_context_state")})
        with patch("fantasy_shared_league_store.save_shared_league", side_effect=RuntimeError("store down")):
            entry, bctx, err = self.accept(barry, BARRY, league_id, invite["invite_id"], "Barry")
        self.assertIsNone(entry)
        self.assertIn("could not be saved to the shared league", err)
        self.assertEqual({k: barry.get(k) for k in before}, before)
        stored = next(i for i in self.doc(league_id)["league_invites"] if i["invite_id"] == invite["invite_id"])
        self.assertEqual(stored["status"], "pending")

    def test_barrys_recovered_copy_is_left_untouched_by_accepting(self) -> None:
        from fantasy_league_context import resolve_canonical_save_ids, save_live_draft_league_context
        from shared_draft_recovery import RECOVERED_FLAG, ROOM_KEY_FIELD

        danny = hosted._signed_in(DANNY)
        _entry, ctx, league_id = self.create(danny)
        invite = self.invite_barry(danny, ctx)
        barry = hosted._signed_in(BARRY)
        with self.on(), self.as_account(BARRY):
            save_live_draft_league_context(barry, completed_room(), my_team_name="Barry",
                                           draft_name="My Fantasy League — Barry", save_only=True,
                                           draft_id="room-da9e78")
        from fantasy_league_context import compute_save_draft_fingerprint

        doc = self.doc(league_id)
        cfg = dict(barry.get("draft_shared_settings") or {})
        same_draft = compute_save_draft_fingerprint(league_rosters=doc["league_rosters"], config=cfg,
                                                    fantasy_format=str(cfg.get("fantasy_format") or ""))
        archives = list_draft_archives(barry)
        for row in archives:
            if row["draft_id"] == "room-da9e78":
                # The recovered copy is the same draft: give it the fingerprint accepting computes.
                row[ROOM_KEY_FIELD], row[RECOVERED_FLAG], row["draft_fingerprint"] = "DA9E78", True, same_draft
        barry["draft_archive_teams"] = archives
        recovered_before = copy.deepcopy(get_draft_archive(barry, "room-da9e78"))
        matched, *_ = resolve_canonical_save_ids(barry, league_rosters=doc["league_rosters"], config=cfg,
                                                 fantasy_format=str(cfg.get("fantasy_format") or ""))
        self.assertEqual(matched, "room-da9e78")  # accepting would have reused (rewritten) it
        entry, _bctx, err = self.accept(barry, BARRY, league_id, invite["invite_id"], "Barry")
        self.assertEqual(err, "")
        self.assertNotEqual(entry["draft_id"], "room-da9e78")
        self.assertEqual(get_draft_archive(barry, "room-da9e78"), recovered_before)
        self.assertEqual(sorted(e["draft_id"] for e in list_draft_archives(barry)),
                         sorted(["room-da9e78", entry["draft_id"]]))


class InvitePanelLeagueChoiceTests(_Case):
    def test_every_league_danny_runs_is_offered_the_new_one_first(self) -> None:
        danny = hosted._signed_in(DANNY)
        older = hosted._invite_suite._seed_imported_league(danny, user_id=DANNY["suite"], workspace=DANNY["workspace"])
        _entry, ctx, league_id = self.create(danny, keep_current_active=True)
        danny["_live_draft_shared_league_create_completed"] = {"r1": {"context_id": ctx["league_context_id"]}}
        with self.on(), self.as_account(DANNY):
            offered = [resolve_canonical_league_id(c) for c in commissioner_invite_contexts(danny)]
        self.assertEqual(offered[0], league_id)
        self.assertIn(resolve_canonical_league_id(older), offered)
        self.assertEqual(len(offered), len(set(offered)))


if __name__ == "__main__":
    unittest.main()
