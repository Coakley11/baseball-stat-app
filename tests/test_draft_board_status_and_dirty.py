"""Draft-board restore rules: what counts as a user edit, what "saved" means, how a refused
save is explained (2026-10-28).

An automatic page-load write is not an edit: before this, a guest first run (auth not ready)
marked the draft room locally edited, which stopped the saved board from restoring once sign-in
completed. A banner may say "saved to your account" only when a cloud readback or restore
verified that exact board.
"""

from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

import draft_room_state as drs
from draft_board_reconcile import SAVE_FAILED_STALE, is_stale_error, save_failure_message
from global_fantasy_settings_state import (
    GLOBAL_FORMAT_KEY,
    GLOBAL_TEAM_KEY,
    write_canonical_global_fantasy_settings,
)


def _board(picks: dict[int, str] | None = None, teams=("Daniel", "Team 2"), rounds=2) -> pd.DataFrame:
    board = drs.build_snake_board(list(teams), rounds=rounds)
    for pick, name in (picks or {}).items():
        board.loc[board["Pick"] == pick, "Player"] = name
    return board


class AutomaticWritesAreNotEditsTests(unittest.TestCase):
    def test_first_time_and_unchanged_settings_do_not_mark_the_room_edited(self) -> None:
        session: dict = {}
        write_canonical_global_fantasy_settings(session, format_="5x5 Roto", team="Daniel", reason="page_load")
        write_canonical_global_fantasy_settings(session, format_="5x5 Roto", team="Daniel", reason="page_load")
        self.assertFalse(drs.is_draft_room_locally_dirty(session))

    def test_changing_an_already_set_value_is_an_edit(self) -> None:
        session: dict = {}
        write_canonical_global_fantasy_settings(session, format_="5x5 Roto", team="Daniel", reason="page_load")
        write_canonical_global_fantasy_settings(session, team="Team 2", reason="user")
        self.assertTrue(drs.is_draft_room_locally_dirty(session))
        self.assertEqual(session[GLOBAL_TEAM_KEY], "Team 2")
        session2: dict = {}
        write_canonical_global_fantasy_settings(session2, format_="5x5 Roto", reason="page_load")
        write_canonical_global_fantasy_settings(session2, format_="Points", reason="user")
        self.assertTrue(drs.is_draft_room_locally_dirty(session2))
        self.assertNotEqual(session2[GLOBAL_FORMAT_KEY], "")

    def test_building_the_default_board_is_not_an_edit_but_a_pick_is(self) -> None:
        session: dict = {}
        drs.write_canonical_draft_room_state(session, _board(), reason="ensure_simulator_board", local_edit=True)
        self.assertFalse(drs.is_draft_room_locally_dirty(session))
        drs.write_canonical_draft_room_state(session, _board({1: "Aaron Judge"}), reason="draft_room_pick", local_edit=True)
        self.assertTrue(drs.is_draft_room_locally_dirty(session))

    def test_a_late_cloud_restore_is_allowed_after_automatic_initialization_only(self) -> None:
        saved = {"draft_room_state": drs.table_to_persist_dict(_board({1: "Shohei Ohtani"}), settings={"room_your_team": "Daniel"})}
        fresh: dict = {}
        drs.write_canonical_draft_room_state(fresh, _board(), reason="ensure_simulator_board", local_edit=True)
        self.assertTrue(drs.apply_cloud_draft_room_state_if_allowed(fresh, saved))
        self.assertEqual(drs.table_pick_count(fresh[drs.DRAFT_ROOM_TABLE_KEY]), 1)
        edited: dict = {}
        drs.write_canonical_draft_room_state(edited, _board({2: "Mookie Betts"}), reason="draft_room_pick", local_edit=True)
        self.assertFalse(drs.apply_cloud_draft_room_state_if_allowed(edited, saved))  # unsaved local edit is kept
        self.assertEqual(drs.table_pick_count(edited[drs.DRAFT_ROOM_TABLE_KEY]), 1)


class RestoredBoardOwnershipTests(unittest.TestCase):
    def test_replacing_a_board_drops_the_old_boards_ownership_stamp(self) -> None:
        from live_draft_navigation import SIMULATOR_BOARD_OWNERSHIP_KEY

        session = {SIMULATOR_BOARD_OWNERSHIP_KEY: {"simulator_board_fingerprint": "of-the-old-board"}}
        drs.apply_restored_board_to_session(session, _board({1: "Aaron Judge"}))
        self.assertNotIn(SIMULATOR_BOARD_OWNERSHIP_KEY, session)


class BoardSaveStatusTests(unittest.TestCase):
    def _signed_in(self):
        return mock.patch.multiple(
            "suite_auth", is_anonymous_guest=mock.DEFAULT
        ), mock.patch("suite_storage_config.cloud_storage_enabled", return_value=True)

    def _status(self, session: dict) -> str:
        with mock.patch("suite_auth.is_anonymous_guest", return_value=False), mock.patch(
            "suite_storage_config.cloud_storage_enabled", return_value=True
        ):
            return drs.simulator_board_save_status(session)

    def test_status_only_claims_saved_after_verification_and_notices_later_changes(self) -> None:
        session = {drs.DRAFT_ROOM_TABLE_KEY: _board()}
        self.assertEqual(self._status(session), drs.BOARD_STATUS_EMPTY)
        session[drs.DRAFT_ROOM_TABLE_KEY] = _board({1: "Aaron Judge"})
        self.assertEqual(self._status(session), drs.BOARD_STATUS_UNVERIFIED)  # a local save attempt is not proof
        drs.mark_board_cloud_verified(session)
        self.assertEqual(self._status(session), drs.BOARD_STATUS_CLOUD_SAVED)
        session[drs.DRAFT_ROOM_TABLE_KEY] = _board({1: "Aaron Judge", 2: "Juan Soto"})
        self.assertEqual(self._status(session), drs.BOARD_STATUS_UNSYNCED)
        session[drs.DRAFT_ROOM_TABLE_KEY] = _board()  # undo everything: still different from what was saved
        self.assertEqual(self._status(session), drs.BOARD_STATUS_UNSYNCED)

    def test_signed_out_or_no_cloud_is_device_only(self) -> None:
        session = {drs.DRAFT_ROOM_TABLE_KEY: _board({1: "Aaron Judge"})}
        with mock.patch("suite_auth.is_anonymous_guest", return_value=True):
            self.assertEqual(drs.simulator_board_save_status(session), drs.BOARD_STATUS_DEVICE_ONLY)
        with mock.patch("suite_auth.is_anonymous_guest", return_value=False), mock.patch(
            "suite_storage_config.cloud_storage_enabled", return_value=False
        ):
            self.assertEqual(drs.simulator_board_save_status(session), drs.BOARD_STATUS_DEVICE_ONLY)

    def test_a_restore_that_skipped_the_board_verifies_nothing(self) -> None:
        cloud = {"draft_room_state": drs.table_to_persist_dict(_board({1: "Shohei Ohtani"}), settings={})}
        local_other = {drs.DRAFT_ROOM_TABLE_KEY: _board({1: "Aaron Judge"})}
        drs.mark_board_cloud_verified(local_other, cloud_state=cloud)
        self.assertNotIn(drs.BOARD_CLOUD_VERIFIED_FP_KEY, local_other)
        same = {drs.DRAFT_ROOM_TABLE_KEY: _board({1: "Shohei Ohtani"})}
        drs.mark_board_cloud_verified(same, cloud_state=cloud)
        self.assertIn(drs.BOARD_CLOUD_VERIFIED_FP_KEY, same)


class SaveFailureMessageTests(unittest.TestCase):
    def test_a_stale_refusal_is_explained_and_never_says_to_just_retry(self) -> None:
        for error in ("stale_or_unhydrated_cloud_revision", "cloud_revision_conflict", "cloud_newer_than_loaded_session"):
            self.assertTrue(is_stale_error(error))
            msg = save_failure_message(error, "default")
            self.assertEqual(msg, SAVE_FAILED_STALE)
            self.assertNotIn("Try again in a moment", msg)
            self.assertIn("Nothing was overwritten", msg)

    def test_other_reasons_keep_their_default_or_get_a_specific_message(self) -> None:
        self.assertEqual(save_failure_message("json_not_serializable", "default"), "default")
        self.assertIn("signed out", save_failure_message("auth_not_ready", "default"))
        self.assertIn("could not be reached", save_failure_message("cloud storage could not be read, so writing was refused", "default"))


if __name__ == "__main__":
    unittest.main()
