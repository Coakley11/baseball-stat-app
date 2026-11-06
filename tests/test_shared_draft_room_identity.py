"""Draft and league identity come from the Shared Draft room, never from roster content (2026-11-05).

QA in baseball-qa-staging: rooms GGLKIU and RT8M61 ended with identical rosters. "Create Shared League"
from RT8M61 matched Danny's saved GGLKIU entry by its roster fingerprint and rewrote it in place (and
its league context); the new league took the fingerprint id league:<fp>. These tests pin the room
identity (shared_draft_identity) and the compatibility rules for records saved before it.
"""

from __future__ import annotations

import copy
import unittest

import tests.test_invite_discovery_hosted_ids as hosted
import tests.test_shared_league_create_accept_reliability as rel
from draft_archive_state import get_draft_archive, list_draft_archives
from fantasy_league_context import (
    CONTEXT_TYPE_REAL_LEAGUE,
    get_league_context,
    get_league_context_for_archive,
    save_live_draft_league_context,
    upsert_league_context,
)
from fantasy_league_identity import compute_draft_fingerprint, resolve_canonical_league_id
from fantasy_shared_league_store import load_shared_league
from live_draft_shared_league import preview_shared_league_creation, save_live_draft_shared_league_context
from shared_draft_identity import ROOM_KEY_FIELD, league_library_id, room_league_id

DANNY, BARRY = hosted.DANNY, hosted.BARRY
LEGACY_LEAGUE = "league:f6e324c5f85617f76d1fa2d4"  # the production Danny-Barry league's id format


class _Case(rel._Case):
    def save_room(self, session: dict, account: dict, code: str, team: str) -> dict:
        session["active_shared_draft_room_code"] = code
        with self.on(), self.as_account(account):
            entry, _ctx = save_live_draft_league_context(session, rel.completed_room(), my_team_name=team,
                                                         draft_name=f"Room {code}", save_only=True)
        return entry

    def league_from_room(self, session: dict, code: str, **kw) -> tuple[dict, dict, str]:
        session["active_shared_draft_room_code"] = code
        with self.on(), self.as_account(DANNY):
            entry, ctx = save_live_draft_shared_league_context(
                session, rel.completed_room(), my_team_name="Danny", league_name=f"League {code}",
                defer_activation=True, assign_team=True, preassign_owners=rel.SEATS, **kw)
        return entry, ctx, resolve_canonical_league_id(ctx)

    def ids(self, session: dict) -> list[str]:
        return sorted(str(e["draft_id"]) for e in list_draft_archives(session))


class TwoRoomsWithIdenticalRostersTests(_Case):
    def test_two_rooms_are_two_entries_and_resaving_updates_its_own(self) -> None:
        danny = hosted._signed_in(DANNY)
        a = self.save_room(danny, DANNY, "AAA111", "Danny")
        b = self.save_room(danny, DANNY, "BBB222", "Danny")
        self.assertEqual(self.ids(danny), ["room-aaa111", "room-bbb222"])
        self.assertEqual(a["draft_fingerprint"], b["draft_fingerprint"])  # same content, still separate
        a_before = copy.deepcopy(get_draft_archive(danny, "room-aaa111"))
        again = self.save_room(danny, DANNY, "BBB222", "Danny")
        self.assertEqual(again["draft_id"], "room-bbb222")
        self.assertEqual(self.ids(danny), ["room-aaa111", "room-bbb222"])          # no duplicate
        self.assertEqual(get_draft_archive(danny, "room-aaa111"), a_before)         # the other room untouched
        for code in ("AAA111", "BBB222"):
            entry = get_draft_archive(danny, f"room-{code.lower()}")
            self.assertEqual(entry[ROOM_KEY_FIELD], code)
            ctx = get_league_context_for_archive(danny, entry)
            self.assertEqual(ctx["metadata"]["source_room_code"], code)

    def test_a_league_from_one_room_never_touches_the_other_rooms_entry_or_active_league(self) -> None:
        danny = hosted._signed_in(DANNY)
        self.save_room(danny, DANNY, "AAA111", "Danny")
        danny["active_draft_archive_id"] = "room-aaa111"
        a_before = copy.deepcopy(get_draft_archive(danny, "room-aaa111"))
        a_ctx_before = copy.deepcopy(get_league_context_for_archive(danny, a_before))
        entry, ctx, league_id = self.league_from_room(danny, "BBB222", keep_current_active=True)
        self.assertEqual(entry["draft_id"], "room-bbb222")
        self.assertEqual(league_id, room_league_id("BBB222"))
        self.assertEqual(get_draft_archive(danny, "room-aaa111"), a_before)
        self.assertEqual(get_league_context_for_archive(danny, a_before), a_ctx_before)
        self.assertEqual(danny["active_draft_archive_id"], "room-aaa111")
        self.assertEqual(self.ids(danny), ["room-aaa111", "room-bbb222"])
        doc = self.doc(league_id)
        self.assertEqual((doc["league_id"], doc.get("source_room_code") or (doc.get("metadata") or {}).get("source_room_code")),
                         (league_id, "BBB222"))

    def test_two_leagues_from_identical_rooms_get_two_league_ids(self) -> None:
        danny = hosted._signed_in(DANNY)
        _e1, _c1, first = self.league_from_room(danny, "AAA111")
        _e2, _c2, second = self.league_from_room(danny, "BBB222")
        self.assertEqual((first, second), (room_league_id("AAA111"), room_league_id("BBB222")))
        self.assertNotEqual(self.doc(first), {})
        self.assertNotEqual(self.doc(second), {})

    def test_the_confirmation_shows_the_id_the_league_will_get(self) -> None:
        from unittest.mock import patch

        session = {"active_shared_draft_room_code": "BBB222"}
        with patch("streamlit.session_state", session, create=True):
            preview = preview_shared_league_creation(rel.completed_room(), my_team_name="Danny")
        self.assertEqual(preview["canonical_league_id"], room_league_id("BBB222"))

    def test_saving_a_room_already_made_into_a_league_does_not_turn_it_back_into_a_draft(self) -> None:
        danny = hosted._signed_in(DANNY)
        _entry, ctx, league_id = self.league_from_room(danny, "BBB222")
        self.save_room(danny, DANNY, "BBB222", "Danny")
        again = get_league_context(danny, ctx["league_context_id"])
        self.assertEqual((again["context_type"], resolve_canonical_league_id(again)), (CONTEXT_TYPE_REAL_LEAGUE, league_id))


class LegacyCompatibilityTests(_Case):
    """Records saved before room identity: random Library ids and fingerprint league ids."""

    def _legacy_league_entry(self, session: dict, *, room_code: str = "DA9E78") -> dict:
        """As the production Danny-Barry league was stored: random entry id, league id league:<fp>,
        source_room_code on the league context, none on the entry, no stored commissioner id; its
        room is stored with Danny as host (2026-11-05: the room host is the commissioner)."""
        hosted.store_room_with_host(room_code, DANNY, (BARRY,))
        session.pop("active_shared_draft_room_code", None)
        with self.on(), self.as_account(DANNY):
            entry, _ = save_live_draft_league_context(session, rel.completed_room(), my_team_name="Danny",
                                                      draft_name="Danny vs Barry League", save_only=True,
                                                      draft_id="9c1d2e3f4a5b")
        ctx = get_league_context_for_archive(session, entry)
        ctx["context_type"] = CONTEXT_TYPE_REAL_LEAGUE
        ctx["league_id"] = LEGACY_LEAGUE
        ctx["metadata"] = {**ctx["metadata"], "league_id": LEGACY_LEAGUE, "draft_fingerprint": compute_draft_fingerprint(ctx),
                           "source_room_code": room_code, "created_from": "live_draft"}
        upsert_league_context(session, ctx)
        return get_draft_archive(session, "9c1d2e3f4a5b")

    def test_a_stored_legacy_league_id_is_kept(self) -> None:
        danny = hosted._signed_in(DANNY)
        entry = self._legacy_league_entry(danny)
        ctx = get_league_context_for_archive(danny, entry)
        self.assertEqual(resolve_canonical_league_id(ctx), LEGACY_LEAGUE)
        # Making a league from that same room again keeps the league's existing id and entry.
        _e, again, league_id = self.league_from_room(danny, "DA9E78")
        self.assertEqual(league_id, LEGACY_LEAGUE)
        self.assertEqual(again["league_context_id"], ctx["league_context_id"])
        self.assertEqual(self.ids(danny), ["9c1d2e3f4a5b"])

    def test_a_legacy_entry_without_room_proof_is_never_merged(self) -> None:
        danny = hosted._signed_in(DANNY)
        danny.pop("active_shared_draft_room_code", None)
        with self.on(), self.as_account(DANNY):
            old, _ = save_live_draft_league_context(danny, rel.completed_room(), my_team_name="Danny",
                                                    draft_name="Old save", save_only=True)
        old_before = copy.deepcopy(old)
        new = self.save_room(danny, DANNY, "CCC333", "Danny")
        self.assertNotEqual(new["draft_id"], old["draft_id"])
        self.assertEqual(get_draft_archive(danny, old["draft_id"])["draft_name"], old_before["draft_name"])
        self.assertEqual(len(list_draft_archives(danny)), 2)

    def test_a_legacy_entry_of_the_same_room_is_updated_not_duplicated(self) -> None:
        danny = hosted._signed_in(DANNY)
        legacy = self._legacy_league_entry(danny, room_code="DDD444")
        self.assertEqual(get_draft_archive(danny, legacy["draft_id"]).get(ROOM_KEY_FIELD), None)
        # Its league context proves the room: a plain save of that room keeps the league as it is.
        self.save_room(danny, DANNY, "DDD444", "Danny")
        self.assertEqual(self.ids(danny), ["9c1d2e3f4a5b"])
        ctx = get_league_context_for_archive(danny, get_draft_archive(danny, "9c1d2e3f4a5b"))
        self.assertEqual(resolve_canonical_league_id(ctx), LEGACY_LEAGUE)


class AcceptIdentityTests(_Case):
    def test_accepting_never_rewrites_another_draft_with_the_same_players(self) -> None:
        danny = hosted._signed_in(DANNY)
        _entry, ctx, league_id = self.league_from_room(danny, "BBB222")
        invite = self.invite_barry(danny, ctx)
        barry = hosted._signed_in(BARRY)
        own = self.save_room(barry, BARRY, "AAA111", "Barry")   # his other room, identical players
        own_before = copy.deepcopy(get_draft_archive(barry, own["draft_id"]))
        barry.pop("active_shared_draft_room_code", None)
        entry, bctx, err = self.accept(barry, BARRY, league_id, invite["invite_id"], "Barry")
        self.assertEqual(err, "")
        self.assertEqual(entry["draft_id"], league_library_id(league_id))
        self.assertEqual(get_draft_archive(barry, own["draft_id"]), own_before)
        self.assertEqual(self.ids(barry), sorted([own["draft_id"], league_library_id(league_id)]))
        self.assertEqual(resolve_canonical_league_id(bctx), league_id)

    def test_barrys_own_copy_is_not_hidden_by_a_league_he_has_not_joined(self) -> None:
        import fantasy_shared_league_authz as authz

        danny = hosted._signed_in(DANNY)
        self.league_from_room(danny, "BBB222")
        barry = hosted._signed_in(BARRY)
        own = self.save_room(barry, BARRY, "BBB222", "Barry")  # his own save of the same room
        with self.on(), self.as_account(BARRY):
            ctx = get_league_context_for_archive(barry, own)
            self.assertFalse(authz.league_copy_hidden(barry, ctx))
            from draft_archive_visibility import list_visible_draft_archives

            self.assertIn(own["draft_id"], [e["draft_id"] for e in list_visible_draft_archives(barry)])

    def test_a_legacy_league_accept_keeps_the_recovered_copy_and_its_room(self) -> None:
        from shared_draft_recovery import RECOVERED_FLAG

        danny = hosted._signed_in(DANNY)
        legacy = LegacyCompatibilityTests._legacy_league_entry(self, danny)
        ctx = get_league_context_for_archive(danny, legacy)
        with self.on(), self.as_account(DANNY):
            from fantasy_shared_league_store import push_league_context_to_shared

            push_league_context_to_shared(danny, ctx)
        invite = self.invite_barry(danny, ctx)
        barry = hosted._signed_in(BARRY)
        rec = self.save_room(barry, BARRY, "DA9E78", "Barry")
        archives = list_draft_archives(barry)
        for row in archives:
            if row["draft_id"] == rec["draft_id"]:
                row[RECOVERED_FLAG] = True
        barry["draft_archive_teams"] = archives
        rec_before = copy.deepcopy(get_draft_archive(barry, rec["draft_id"]))
        barry.pop("active_shared_draft_room_code", None)
        entry, _bctx, err = self.accept(barry, BARRY, LEGACY_LEAGUE, invite["invite_id"], "Barry")
        self.assertEqual(err, "")
        self.assertEqual(entry["draft_id"], league_library_id(LEGACY_LEAGUE))
        self.assertEqual(get_draft_archive(barry, rec["draft_id"]), rec_before)
        self.assertEqual(rec_before[ROOM_KEY_FIELD], "DA9E78")
        self.assertEqual(self.doc(LEGACY_LEAGUE)["league_id"], LEGACY_LEAGUE)  # not renamed or duplicated


if __name__ == "__main__":
    unittest.main()
