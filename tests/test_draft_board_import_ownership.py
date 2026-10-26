"""An applied draft import stays the active Draft Room board: next rerun, Save, refresh.

Regression: the board was stamped with its owner only in session, so the account scrub
(scrub_simulator_runtime_for_current_account, run on every prepare) discarded it as
"legacy_or_foreign_board" — at once for a signed-out session (no stamp possible), and after
a refresh for a signed-in one (the stamp was not persisted). The Draft Room then rebuilt an
empty board from League setup, so the banner said 0 picks and Save failed.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state
from draft_import_pipeline import apply_validated_import_to_board
from draft_room_state import (
    DRAFT_ROOM_STATE_KEY,
    DRAFT_ROOM_TABLE_KEY,
    ensure_simulator_board_for_settings,
    prepare_draft_room_state,
    save_draft_board_now,
    table_pick_count,
)
from live_draft_navigation import (
    PERSISTED_OWNERSHIP_FIELD,
    SIMULATOR_BOARD_OWNERSHIP_KEY,
    scrub_simulator_runtime_for_current_account,
)
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_ID_KEY

WORKSPACE = "coakley11"


DEVICE = "qa-device-one"


def _identity(
    *, signed_in: bool, workspace: str = WORKSPACE, external: str = "coakley11", device: str = DEVICE
) -> dict:
    out = {"_suite_active_workspace_id": workspace, "_suite_owned_workspace_id": workspace}
    if signed_in:
        out.update({AUTH_USER_ID_KEY: f"user:{external}", AUTH_EXTERNAL_ID_KEY: external})
    else:
        # Local install (sign-in disabled): the signed-out owner is this install's device id.
        out["_suite_device_id"] = device
    return out


def _import_board(picks: int = 40, teams: int = 4, prefix: str = "Player") -> pd.DataFrame:
    rows = []
    for i in range(picks):
        rnd, slot = divmod(i, teams)
        order = range(1, teams + 1) if rnd % 2 == 0 else range(teams, 0, -1)
        rows.append({"Round": rnd + 1, "Pick": i + 1, "Team": f"Team {list(order)[slot]}", "Player": f"{prefix} {i + 1}"})
    return pd.DataFrame(rows)


def _session(*, signed_in: bool, **identity) -> dict:
    # League setup disagrees with the import (2 teams x 20 rounds vs 4 x 10) — the real case.
    return {
        "active_page": "Draft Room Simulator",
        "main_sidebar_page": "Draft Room Simulator",
        "room_team_count": 2,
        "room_rounds": 20,
        "room_team_names": "Daniel\nTeam 2",
        **_identity(signed_in=signed_in, **identity),
    }


def _apply(session: dict, board: pd.DataFrame) -> None:
    with patch("draft_room_state.persist_draft_board_to_storage", return_value={}):
        apply_validated_import_to_board(MagicMock(), session, board, rerun=False)


def _next_rerun(session: dict) -> pd.DataFrame:
    """What the Draft Room does at the top of the next script run."""
    scrub_simulator_runtime_for_current_account(session, reason="prepare_baseball_workspace")
    prepare_draft_room_state(session)
    return ensure_simulator_board_for_settings(session)


def _refresh(session: dict, **identity) -> dict:
    st = MagicMock()
    st.session_state = session
    state = build_baseball_disk_state(st)
    st2 = MagicMock()
    st2.session_state = {"active_page": "Draft Room Simulator", "main_sidebar_page": "Draft Room Simulator", **identity}
    apply_baseball_disk_state(st2, state)
    return st2.session_state


def _players(table) -> list[str]:
    return [p for p in table["Player"].astype(str).tolist() if p.strip()]


class AppliedImportIsCanonicalTests(unittest.TestCase):
    def _assert_imported(self, table, board) -> None:
        self.assertEqual(table_pick_count(table), table_pick_count(board))
        self.assertEqual(_players(table), _players(board))
        self.assertEqual(sorted(set(table["Team"])), sorted(set(board["Team"])))

    def test_signed_out_import_survives_the_next_rerun(self) -> None:
        session = _session(signed_in=False)
        board = _import_board()
        _apply(session, board)
        self._assert_imported(_next_rerun(session), board)
        self._assert_imported(session[DRAFT_ROOM_TABLE_KEY], board)

    def test_signed_in_import_survives_the_next_rerun(self) -> None:
        session = _session(signed_in=True)
        board = _import_board()
        _apply(session, board)
        self._assert_imported(_next_rerun(session), board)

    def test_import_survives_refresh_signed_in_and_signed_out(self) -> None:
        for signed_in in (True, False):
            with self.subTest(signed_in=signed_in):
                session = _session(signed_in=signed_in)
                board = _import_board()
                _apply(session, board)
                _next_rerun(session)
                restored = _refresh(session, **_identity(signed_in=signed_in))
                self.assertIsInstance(restored[DRAFT_ROOM_STATE_KEY].get(PERSISTED_OWNERSHIP_FIELD), dict)
                self._assert_imported(_next_rerun(restored), board)
                self.assertIsInstance(restored.get(SIMULATOR_BOARD_OWNERSHIP_KEY), dict)
                # and a second refresh (stamp adopted, persisted again)
                again = _refresh(restored, **_identity(signed_in=signed_in))
                self._assert_imported(_next_rerun(again), board)

    def test_small_import(self) -> None:
        session = _session(signed_in=False)
        board = _import_board(picks=3, teams=2)
        _apply(session, board)
        table = _next_rerun(session)
        self.assertEqual(_players(table), ["Player 1", "Player 2", "Player 3"])

    def test_save_draft_board_now_saves_exactly_the_imported_board(self) -> None:
        session = _session(signed_in=False)
        board = _import_board()
        _apply(session, board)
        shown = _next_rerun(session)
        st = MagicMock()
        st.session_state = session
        with patch("baseball_persistent_state.force_save_baseball_state", return_value=True):
            with patch("suite_cloud_state.load_cloud_full_session", return_value=({}, None)):
                with patch("draft_room_state.save_draft_board_direct_to_cloud", return_value={"saved_cloud": False}):
                    trace = save_draft_board_now(st, session, board=shown)
        self.assertTrue(trace.get("saved"))
        self.assertEqual(trace.get("saved_pick_count"), 40)
        self._assert_imported(session[DRAFT_ROOM_TABLE_KEY], board)
        self._assert_imported(_next_rerun(_refresh(session, **_identity(signed_in=False))), board)

    def test_second_import_replaces_the_first_through_refresh(self) -> None:
        session = _session(signed_in=True)
        _apply(session, _import_board(prefix="First"))
        _next_rerun(session)
        second = _import_board(picks=12, teams=3, prefix="Second")
        _apply(session, second)
        _next_rerun(session)
        restored = _refresh(session, **_identity(signed_in=True))
        table = _next_rerun(restored)
        self._assert_imported(table, second)
        self.assertFalse(any(p.startswith("First") for p in _players(table)))


class OwnershipStillIsolatesAccountsTests(unittest.TestCase):
    """Persisting the stamp must not let a board cross accounts or workspaces."""

    def _stamped_state(self, *, signed_in: bool) -> dict:
        session = _session(signed_in=signed_in)
        _apply(session, _import_board())
        _next_rerun(session)
        return session

    def _restored_picks(self, session: dict, **identity) -> tuple[int, dict]:
        restored = _refresh(session, **identity)
        scrub = scrub_simulator_runtime_for_current_account(restored, reason="prepare_baseball_workspace")
        return table_pick_count(restored.get(DRAFT_ROOM_TABLE_KEY)), scrub

    def test_another_account_cannot_restore_the_board(self) -> None:
        picks, scrub = self._restored_picks(
            self._stamped_state(signed_in=True), **_identity(signed_in=True, external="someoneelse")
        )
        self.assertEqual(picks, 0)
        self.assertEqual(scrub.get("reason"), "foreign_board_owner_mismatch")

    def test_signed_out_board_is_not_adopted_after_sign_in(self) -> None:
        picks, scrub = self._restored_picks(self._stamped_state(signed_in=False), **_identity(signed_in=True))
        self.assertEqual(picks, 0)
        self.assertEqual(scrub.get("reason"), "foreign_board_owner_mismatch")

    def test_other_workspace_cannot_restore_the_board(self) -> None:
        picks, scrub = self._restored_picks(
            self._stamped_state(signed_in=False), **_identity(signed_in=False, workspace="daniel_cohen11")
        )
        self.assertEqual(picks, 0)
        self.assertEqual(scrub.get("reason"), "foreign_board_workspace_mismatch")

    def test_stamp_for_a_different_board_does_not_count(self) -> None:
        session = self._stamped_state(signed_in=True)
        restored = _refresh(session, **_identity(signed_in=True))
        restored[DRAFT_ROOM_TABLE_KEY] = _import_board(prefix="Swapped")
        scrub = scrub_simulator_runtime_for_current_account(restored, reason="prepare_baseball_workspace")
        self.assertTrue(scrub.get("cleared"))
        self.assertEqual(table_pick_count(restored.get(DRAFT_ROOM_TABLE_KEY)), 0)

    def test_signed_out_board_needs_the_same_device_not_just_workspace_and_board(self) -> None:
        session = self._stamped_state(signed_in=False)
        picks, scrub = self._restored_picks(session, **_identity(signed_in=False, device="another-install"))
        self.assertEqual(picks, 0)
        self.assertEqual(scrub.get("reason"), "foreign_board_anonymous_owner_mismatch")
        picks, scrub = self._restored_picks(session, **_identity(signed_in=False))
        self.assertEqual(picks, 40)

    def test_signed_out_board_without_any_principal_is_not_ownable(self) -> None:
        session = _session(signed_in=False)
        session.pop("_suite_device_id")
        with patch.dict("os.environ", {"BASEBALL_DEVICE_ID": ""}), patch(
            "baseball_persistent_state._DEVICE_ID_FILE", Path("no-such-device-file.txt")
        ):
            _apply(session, _import_board())
            self.assertNotIn(SIMULATOR_BOARD_OWNERSHIP_KEY, session)
            self.assertEqual(table_pick_count(_next_rerun(session)), 0)

    def test_signed_in_board_is_not_visible_once_signed_out(self) -> None:
        picks, scrub = self._restored_picks(self._stamped_state(signed_in=True), **_identity(signed_in=False))
        self.assertEqual(picks, 0)
        self.assertEqual(scrub.get("reason"), "foreign_board_owner_mismatch")

    def test_legacy_signed_out_daniel_workspace_is_not_stamped(self) -> None:
        session = _session(signed_in=False, workspace="daniel")
        _apply(session, _import_board())
        self.assertNotIn(SIMULATOR_BOARD_OWNERSHIP_KEY, session)
        self.assertNotIn(PERSISTED_OWNERSHIP_FIELD, session[DRAFT_ROOM_STATE_KEY])
        self.assertEqual(table_pick_count(_next_rerun(session)), 40)



@patch("suite_auth.is_auth_enabled", return_value=True)
class HostedSignedOutOwnershipTests(unittest.TestCase):
    """Sign-in enabled: signed-out visitors share a workspace, so a signed-out board belongs to
    its browser session only — never to whoever else is signed out in that workspace."""

    def _hosted_session(self) -> dict:
        session = _session(signed_in=False)
        session.pop("_suite_device_id")
        return session

    def test_board_survives_reruns_in_the_same_session(self, _auth) -> None:
        session = self._hosted_session()
        _apply(session, _import_board())
        for _ in range(3):
            self.assertEqual(table_pick_count(_next_rerun(session)), 40)

    def test_another_signed_out_browser_does_not_inherit_it(self, _auth) -> None:
        session = self._hosted_session()
        _apply(session, _import_board())
        _next_rerun(session)
        other = _refresh(session, **{k: v for k, v in _identity(signed_in=False).items() if k != "_suite_device_id"})
        scrub = scrub_simulator_runtime_for_current_account(other, reason="prepare_baseball_workspace")
        self.assertEqual(scrub.get("reason"), "foreign_board_anonymous_owner_mismatch")
        self.assertEqual(table_pick_count(other.get(DRAFT_ROOM_TABLE_KEY)), 0)

    def test_signing_in_does_not_adopt_it(self, _auth) -> None:
        session = self._hosted_session()
        _apply(session, _import_board())
        _next_rerun(session)
        restored = _refresh(session, **_identity(signed_in=True))
        scrub = scrub_simulator_runtime_for_current_account(restored, reason="prepare_baseball_workspace")
        self.assertEqual(scrub.get("reason"), "foreign_board_owner_mismatch")
        self.assertEqual(table_pick_count(restored.get(DRAFT_ROOM_TABLE_KEY)), 0)


if __name__ == "__main__":
    unittest.main()
