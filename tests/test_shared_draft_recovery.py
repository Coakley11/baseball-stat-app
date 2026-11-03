"""Recover a completed Shared Draft into the Saved Draft Library from its room record.

Lifecycle items 1-10 and 15 of the 2026-11-02 request. The room is the owner's case: room DA9E78,
teams Danny and Barry, 4 of 4 picks (Danny: Matt Olson, Barry: Cal Raleigh, Barry: Pete Alonso,
Danny: Salvador Perez). Account saves are recorded, not sent anywhere.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from draft_archive_state import list_draft_archives
from draft_room_shared_state import LocalFileSharedRoomStore
from fantasy_league_context import save_live_draft_league_context
from shared_draft_recovery import (
    ROOM_KEY_FIELD,
    list_recoverable_rooms,
    load_recovery_preview,
    recover_completed_shared_draft,
)

CODE = "DA9E78"
PICKS = [("Danny", "Matt Olson", "olsonma02"), ("Barry", "Cal Raleigh", "raleica01"),
         ("Barry", "Pete Alonso", "alonspe01"), ("Danny", "Salvador Perez", "perezsa02")]


def room_document(*, complete: bool = True, revision: int = 11) -> dict:
    board = [
        {"Pick": i, "Round": (i + 1) // 2, "Fantasy Team": team, "Team": team, "Player": player,
         "fullName": player, "playerID": pid, "Primary Position": "1B" if "Ols" in player or "Alon" in player else "C"}
        for i, (team, player, pid) in enumerate(PICKS[: 4 if complete else 3], start=1)
    ]
    rosters = {"Danny": [], "Barry": []}
    for row in board:
        rosters[row["Fantasy Team"]].append({"fullName": row["Player"], "playerID": row["playerID"],
                                             "Primary Position": row["Primary Position"]})
    status = "complete" if complete else "in_progress"
    return {
        "room_code": CODE,
        "revision": revision,
        "status": status,
        "host_user_id": "uuid-danny",
        "host_participant_id": "uuid-danny",
        "participants": {
            "uuid-danny": {"participant_id": "uuid-danny", "user_id": "uuid-danny", "assigned_team": "Danny"},
            "pid-barry": {"participant_id": "pid-barry", "user_id": "uuid-barry", "assigned_team": "Barry",
                          "email": "barry@example.com"},
        },
        "room": {
            "status": status,
            "teams": ["Danny", "Barry"],
            "config": {"league_name": "Danny vs Barry", "fantasy_format": "5x5 Roto", "scoring_type": "5x5 Roto",
                       "num_teams": 2, "picks_per_team": 2, "slots": {"C": 1, "1B": 1}, "teams": ["Danny", "Barry"]},
            "pick_order": [{"Pick": i, "Round": (i + 1) // 2, "Team": t} for i, t in
                           enumerate(["Danny", "Barry", "Barry", "Danny"], start=1)],
            "draft_board": board,
            "rosters": rosters,
        },
    }


def signed_in(account: str) -> dict:
    return {"_suite_auth_session": True, "_suite_auth_user_id": f"uuid-{account}",
            "_suite_cloud_user_id": f"uuid-{account}", "_suite_auth_external_id": account,
            "_suite_owned_workspace_id": account, "_suite_active_workspace_id": account}


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = LocalFileSharedRoomStore(root=self.root)
        self.write_room(room_document())
        self.saves: list[tuple[int, str]] = []
        save = mock.patch("baseball_persistent_state.force_save_baseball_state", side_effect=self._record_save)
        save.start()
        self.addCleanup(save.stop)

    def _record_save(self, st, reason="", **_kw):
        self.saves.append((id(st.session_state), str(reason)))
        return True

    def write_room(self, doc: dict) -> None:
        (self.root / f"{CODE}.json").write_text(json.dumps(doc), encoding="utf-8")

    def room_bytes(self) -> bytes:
        return (self.root / f"{CODE}.json").read_bytes()

    def st(self, session: dict):
        st = mock.MagicMock()
        st.session_state = session
        return st

    def recover(self, session: dict, *, confirmed: bool = True, revision: int | None = None):
        preview = load_recovery_preview(session, CODE, store=self.store)
        with mock.patch("suite_cloud_state._streamlit_session", return_value=session):
            return recover_completed_shared_draft(
                self.st(session), session, CODE, confirmed=confirmed,
                expected_revision=preview.get("revision", 0) if revision is None else revision, store=self.store,
            )


class StoredRoomTests(_Case):
    def test_the_preview_shows_the_four_stored_picks_in_order(self) -> None:
        preview = load_recovery_preview(signed_in("danny"), CODE, store=self.store)
        self.assertTrue(preview["ok"], preview["problems"])
        self.assertEqual([(p["team"], p["player"]) for p in preview["picks"]], [(t, p) for t, p, _ in PICKS])
        self.assertEqual((preview["status"], preview["revision"], preview["team"]), ("complete", 11, "Danny"))
        self.assertEqual(preview["missing"], [])

    def test_missing_information_is_named_not_invented(self) -> None:
        doc = room_document()
        doc["room"]["draft_board"][2].pop("playerID")
        doc["room"]["config"].pop("slots")
        self.write_room(doc)
        preview = load_recovery_preview(signed_in("danny"), CODE, store=self.store)
        self.assertIn("pick 3 (Pete Alonso): player id", preview["missing"])
        self.assertIn("roster slots", preview["missing"])
        self.assertEqual(preview["settings"]["roster_slots"], {})  # shown as not recorded, not defaulted

    def test_an_unfinished_room_cannot_be_recovered(self) -> None:
        self.write_room(room_document(complete=False))
        session = signed_in("danny")
        self.assertEqual(list_recoverable_rooms(session, store=self.store), [])
        self.assertFalse(load_recovery_preview(session, CODE, store=self.store)["ok"])
        self.assertFalse(self.recover(session)["ok"])
        self.assertEqual(list_draft_archives(session), [])


class RecoveryLifecycleTests(_Case):
    def test_1_a_normal_save_with_the_same_picks_is_flagged_and_never_silently_duplicated(self) -> None:
        session = signed_in("danny")
        save_live_draft_league_context(session, room_document()["room"], my_team_name="Danny", draft_name="Saved normally", save_only=True)
        preview = load_recovery_preview(session, CODE, store=self.store)
        self.assertEqual(preview["existing_draft_id"], "")  # content alone is not this room's entry
        self.assertTrue(preview["similar_draft_id"])        # but it is shown as possibly the same draft
        out = self.recover(session)
        self.assertTrue(out.get("similar_in_library"))
        self.assertEqual([e["draft_name"] for e in list_draft_archives(session)], ["Saved normally"])
        with mock.patch("suite_cloud_state._streamlit_session", return_value=session):
            kept = recover_completed_shared_draft(self.st(session), session, CODE, confirmed=True, expected_revision=11,
                                                  keep_alongside_similar=True, store=self.store)
        self.assertTrue(kept["ok"], kept)  # only on an explicit "keep both"
        self.assertEqual(sorted(e["draft_name"] for e in list_draft_archives(session)),
                         sorted(["Saved normally", "Danny vs Barry — Danny"]))

    def test_two_rooms_with_identical_picks_are_two_separate_entries(self) -> None:
        other = room_document()
        other["room_code"] = "BB0002"
        (self.root / "BB0002.json").write_text(json.dumps(other), encoding="utf-8")
        session = signed_in("danny")
        self.assertTrue(self.recover(session)["ok"])
        second = load_recovery_preview(session, "BB0002", store=self.store)
        self.assertEqual((second["existing_draft_id"], second["similar_draft_id"]), ("", ""))  # not confused
        with mock.patch("suite_cloud_state._streamlit_session", return_value=session):
            out = recover_completed_shared_draft(self.st(session), session, "BB0002", confirmed=True, expected_revision=11,
                                                 store=self.store)
        self.assertTrue(out["ok"], out)
        self.assertEqual(sorted(e["draft_id"] for e in list_draft_archives(session)), ["room-bb0002", "room-da9e78"])
        self.assertEqual(sorted(e[ROOM_KEY_FIELD] for e in list_draft_archives(session)), ["BB0002", CODE])

    def test_2_and_3_room_complete_library_save_refused_then_recovered_in_a_new_session(self) -> None:
        # The original tab's save was refused and that tab is gone: a brand-new session recovers.
        session = signed_in("danny")
        rooms = list_recoverable_rooms(session, store=self.store)
        self.assertEqual([(r["room_code"], r["team"], r["role"]) for r in rooms], [(CODE, "Danny", "commissioner")])
        out = self.recover(session)
        self.assertTrue(out["ok"], out)
        entry = next(e for e in list_draft_archives(session) if e["draft_id"] == out["draft_id"])
        self.assertEqual((entry["team_name"], entry[ROOM_KEY_FIELD]), ("Danny", CODE))
        self.assertEqual([r["Player"] for r in entry["draft_board"]], [p for _, p, _ in PICKS])
        self.assertEqual(self.saves, [(id(session), "shared_draft_recovered")])

    def test_4_commissioner_recovery(self) -> None:
        out = self.recover(signed_in("danny"))
        self.assertTrue(out["ok"])
        self.assertEqual(out["team"], "Danny")

    def test_5_participant_recovery_keeps_that_participants_team(self) -> None:
        session = signed_in("barry")
        self.assertEqual(list_recoverable_rooms(session, store=self.store)[0]["role"], "participant")
        out = self.recover(session)
        self.assertTrue(out["ok"], out)
        entry = list_draft_archives(session)[0]
        self.assertEqual(entry["team_name"], "Barry")
        names = sorted(str(r.get("fullName") or r.get("Player") or r.get("player_name") or "") for r in entry["players"])
        self.assertEqual(names, ["Cal Raleigh", "Pete Alonso"])  # Barry's own picks, not Danny's

    def test_7_and_8_the_room_and_other_libraries_are_untouched(self) -> None:
        before = self.room_bytes()
        barry = signed_in("barry")
        save_live_draft_league_context(barry, room_document()["room"], my_team_name="Barry", draft_name="Barry's own", save_only=True)
        barry_before = copy.deepcopy(list_draft_archives(barry))
        with mock.patch.object(LocalFileSharedRoomStore, "save") as room_save, mock.patch.object(
            LocalFileSharedRoomStore, "save_if_revision"
        ) as room_cas, mock.patch("fantasy_shared_league_store.save_shared_league") as league_save:
            self.assertTrue(self.recover(signed_in("danny"))["ok"])
        room_save.assert_not_called()
        room_cas.assert_not_called()
        league_save.assert_not_called()
        self.assertEqual(self.room_bytes(), before)
        self.assertEqual(list_draft_archives(barry), barry_before)
        self.assertNotIn(id(barry), [sid for sid, _ in self.saves])

    def test_9_recovering_twice_creates_one_entry(self) -> None:
        session = signed_in("danny")
        self.assertTrue(self.recover(session)["ok"])
        again = self.recover(session)
        self.assertTrue(again.get("already_in_library"))
        self.assertEqual(len(list_draft_archives(session)), 1)
        self.assertTrue(list_recoverable_rooms(session, store=self.store)[0]["in_library"])

    def test_10_nothing_is_added_or_replaced_without_confirmation(self) -> None:
        session = signed_in("danny")
        self.assertFalse(self.recover(session, confirmed=False)["ok"])
        self.assertEqual(list_draft_archives(session), [])
        self.assertEqual(self.saves, [])
        save_live_draft_league_context(session, room_document()["room"], my_team_name="Danny", draft_name="Mine, renamed", save_only=True)
        out = self.recover(session)
        self.assertFalse(out["ok"])
        self.assertEqual([e["draft_name"] for e in list_draft_archives(session)], ["Mine, renamed"])

    def test_a_room_that_changed_after_the_preview_is_not_recovered(self) -> None:
        session = signed_in("danny")
        out = self.recover(session, revision=10)
        self.assertFalse(out["ok"])
        self.assertIn("changed since the preview", out["error"])

    def test_15_after_recovery_a_restart_and_reopen_still_show_one_entry(self) -> None:
        session = signed_in("danny")
        out = self.recover(session)
        self.assertTrue(out["ok"])
        from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state

        blob = build_baseball_disk_state(self.st(session))
        # A restart: a new session loads the saved workspace, then the account is attached (the order
        # the app uses; see test_draft_library_persist_roundtrip).
        reopened: dict = {}
        apply_baseball_disk_state(self.st(reopened), json.loads(json.dumps(blob, default=str)))
        reopened.update(signed_in("danny"))
        entries = [e for e in list_draft_archives(reopened) if e.get(ROOM_KEY_FIELD) == CODE]
        self.assertEqual(len(entries), 1)
        self.assertTrue(load_recovery_preview(reopened, CODE, store=self.store)["existing_draft_id"])
        self.assertTrue(self.recover(reopened).get("already_in_library"))


class AuthorizationTests(_Case):
    def test_6_an_unrelated_account_cannot_discover_preview_or_recover(self) -> None:
        mallory = signed_in("mallory")
        self.assertEqual(list_recoverable_rooms(mallory, store=self.store), [])
        preview = load_recovery_preview(mallory, CODE, store=self.store)
        self.assertFalse(preview.get("ok"))
        self.assertNotIn("picks", preview)  # nothing of the room is returned
        self.assertEqual(preview["error"], load_recovery_preview(mallory, "NOPE00", store=self.store)["error"])
        self.assertFalse(self.recover(mallory)["ok"])
        self.assertEqual(list_draft_archives(mallory), [])
        self.assertEqual(self.saves, [])

    def test_signed_out_and_lookalike_identities_get_nothing(self) -> None:
        self.assertEqual(list_recoverable_rooms({}, store=self.store), [])
        self.assertFalse(load_recovery_preview({}, CODE, store=self.store)["ok"])
        lookalike = signed_in("someone")
        lookalike.update({"_suite_auth_user_email": "barry@example.com", "_suite_auth_external_id": "barry",
                          "_suite_owned_workspace_id": "barry"})  # same email/name/workspace, other account id
        self.assertEqual(list_recoverable_rooms(lookalike, store=self.store), [])
        self.assertFalse(self.recover(lookalike)["ok"])

    def test_a_forged_confirmation_is_refused_on_the_server(self) -> None:
        session = signed_in("danny")
        with mock.patch("suite_cloud_state._streamlit_session", return_value=session):
            out = recover_completed_shared_draft(self.st(session), session, CODE, confirmed=False, expected_revision=11,
                                                 store=self.store)
        self.assertFalse(out["ok"])
        self.assertEqual(list_draft_archives(session), [])


if __name__ == "__main__":
    unittest.main()


class SupabaseListingTests(unittest.TestCase):
    def test_the_listing_asks_only_for_completed_rooms_and_never_for_boards_or_chat(self) -> None:
        import draft_room_supabase_store as sb

        store = sb.SupabaseSharedRoomStore.__new__(sb.SupabaseSharedRoomStore)
        rows = [{"room_code": CODE, "status": "complete", "host_user_id": "uuid-danny", "participants": {}}]
        with mock.patch.object(sb, "_request", return_value=rows) as request:
            self.assertEqual(store.list_completed_room_heads(limit=50), rows)
        params = request.call_args.kwargs["params"]
        self.assertEqual(params["status"], "in.(complete,completed)")
        self.assertEqual(params["limit"], "50")
        for private in ("draft_board", "rosters", "chat", "shared_room_json,", "pool"):
            self.assertNotIn(private, params["select"])
        with mock.patch.object(sb, "_request", side_effect=RuntimeError("down")):
            self.assertEqual(store.list_completed_room_heads(), [])


class LibraryPagePanelTests(_Case):
    """The real Saved Draft Library page: find, preview, confirm, recover."""

    def test_the_panel_recovers_only_after_confirmation(self) -> None:
        from streamlit.testing.v1 import AppTest

        room_before = self.room_bytes()
        fixture = Path(__file__).resolve().parent / "fixtures" / "library_recovery_app.py"
        at = AppTest.from_file(str(fixture), default_timeout=120)
        for key, value in signed_in("danny").items():
            at.session_state[key] = value
        at.session_state["_fx_room_root"] = str(self.root)
        with mock.patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}):
            at.run()
            self.assertFalse(at.exception, [str(e.value)[:300] for e in at.exception])
            at.button(key="sdr_find").click().run()
            self.assertIn(CODE, at.selectbox(key="sdr_choice").value)
            at.button(key="sdr_preview").click().run()
            self.assertIn("Matt Olson", str([d.value for d in at.dataframe]))
            at.button(key="sdr_recover").click().run()  # forged click while unconfirmed
            self.assertEqual(list(at.session_state["_fx_saves"]) if "_fx_saves" in at.session_state else [], [])
            at.checkbox(key="sdr_confirm").check().run()
            at.button(key="sdr_recover").click().run()
            self.assertFalse(at.exception, [str(e.value)[:300] for e in at.exception])
        self.assertIn("shared_draft_recovered", list(at.session_state["_fx_saves"]))
        archives = at.session_state["draft_archive_teams"]
        self.assertEqual([(a["team_name"], a[ROOM_KEY_FIELD]) for a in archives], [("Danny", CODE)])
        self.assertEqual(self.room_bytes(), room_before)  # the room record is byte-identical


class LibraryVisibilityAfterSaveTests(_Case):
    """With sign-in on, a signed-in account's own Live Draft entry must survive the Library clean-up.

    Found 2026-11-02: the basic Save to Draft Library entry had no owner, failed visibility, and the
    next clean-up (Library visit, sign-in) deleted it. The save now records the saving account as
    the owner of its own team (session id only)."""

    def setUp(self) -> None:
        super().setUp()
        from tests.test_fantasy_trade_proposals import _as_user

        for p in (mock.patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}),
                  mock.patch("suite_auth.is_authenticated", return_value=True)):
            p.start()
            self.addCleanup(p.stop)
        self._as_user = _as_user

    def _kept_by_cleanup(self, session: dict, account: str) -> bool:
        from draft_archive_visibility import prune_invisible_shared_league_state

        with self._as_user(f"uuid-{account}"):
            prune_invisible_shared_league_state(session)
        return bool(list_draft_archives(session))

    def test_a_normal_live_draft_save_survives_the_library_cleanup(self) -> None:
        session = signed_in("danny")
        with self._as_user("uuid-danny"):
            save_live_draft_league_context(session, room_document()["room"], my_team_name="Danny", save_only=True)
        self.assertTrue(self._kept_by_cleanup(session, "danny"))

    def test_a_recovered_draft_survives_the_cleanup_and_stays_hidden_from_other_accounts(self) -> None:
        from draft_archive_visibility import list_visible_draft_archives

        session = signed_in("barry")
        with self._as_user("uuid-barry"):
            self.assertTrue(self.recover(session)["ok"])
        self.assertTrue(self._kept_by_cleanup(session, "barry"))
        other = signed_in("mallory")
        other["draft_archive_teams"] = copy.deepcopy(session["draft_archive_teams"])
        other["fantasy_league_context_state"] = copy.deepcopy(session["fantasy_league_context_state"])
        with self._as_user("uuid-mallory"):
            self.assertEqual(list_visible_draft_archives(other), [])

    def test_a_confirmed_recovery_after_deleting_the_recovered_copy_lifts_only_that_marker(self) -> None:
        from draft_archive_state import DELETED_DRAFT_ARCHIVE_IDS_KEY

        session = signed_in("danny")
        with self._as_user("uuid-danny"):
            first = self.recover(session)
            self.assertTrue(first["ok"])
            session["draft_archive_teams"] = []
            session[DELETED_DRAFT_ARCHIVE_IDS_KEY] = [first["draft_id"], "someone-else"]  # the copy was deleted
            again = self.recover(session)
        self.assertTrue(again["ok"], again)
        self.assertEqual(again["draft_id"], first["draft_id"])  # the same room id
        self.assertEqual(session.get(DELETED_DRAFT_ARCHIVE_IDS_KEY), ["someone-else"])  # only its own marker lifted
