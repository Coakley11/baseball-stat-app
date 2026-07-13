"""Same-browser account transition must not leak private Draft Simulator resume."""

from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from live_draft_navigation import (
    SIMULATOR_BOARD_OWNERSHIP_KEY,
    SIMULATOR_RESUME_IDENTITY_KEY,
    clear_private_baseball_simulator_runtime,
    collect_simulator_resume_diagnostics,
    get_draft_return_context,
    scrub_simulator_runtime_for_current_account,
    stamp_simulator_board_ownership,
)
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_ID_KEY, _clear_auth_session, _persist_auth_session


def _sim_board(*, team: str = "Donny", picks: int = 12) -> pd.DataFrame:
    rows = []
    for i in range(picks):
        rows.append(
            {
                "Round": (i // 2) + 1,
                "Pick": i + 1,
                "Team": team if i % 2 == 0 else "Team B",
                "Fantasy Team": team if i % 2 == 0 else "Team B",
                "Player": f"Sim{i}",
            }
        )
    return pd.DataFrame(rows)


def _daniel_session() -> dict:
    return {
        AUTH_USER_ID_KEY: "user:daniel",
        AUTH_EXTERNAL_ID_KEY: "daniel",
        "_suite_auth_user_email": "daniel@example.com",
        "_suite_active_workspace_id": "daniel",
        "_suite_owned_workspace_id": "daniel",
        "room_your_team": "Donny",
        "room_team_count": 2,
        "room_rounds": 10,
        "room_format": "5x5 Roto",
        "room_window": "rest_of_season",
        "fantasy_draft_projection_style": "Conservative",
        "draft_shared_settings": {"projection_style": "Conservative"},
        "draft_room_table": _sim_board(team="Donny", picks=12),
        "draft_room_state": {"mode": "draft_room_simulator"},
    }


def _coakley_session() -> dict:
    return {
        AUTH_USER_ID_KEY: "user:coakley11",
        AUTH_EXTERNAL_ID_KEY: "coakley11",
        "_suite_auth_user_email": "coakley11@aol.com",
        "_suite_active_workspace_id": "coakley11",
        "_suite_owned_workspace_id": "coakley11",
    }


def _board_pick_count(session: dict) -> int:
    table = session.get("draft_room_table")
    if table is None:
        return 0
    if hasattr(table, "empty") and table.empty:
        return 0
    if hasattr(table, "columns") and "Player" in getattr(table, "columns", []):
        return int(sum(1 for p in table["Player"].tolist() if str(p).strip()))
    return 0


def _assert_no_donny_simulator_card(testcase: unittest.TestCase, session: dict, ctx) -> None:
    testcase.assertTrue(ctx is None or ctx.get("kind") != "simulator" or ctx.get("user_team") != "Donny")
    if ctx is not None and ctx.get("kind") == "simulator":
        testcase.fail(f"unexpected simulator card: {ctx}")
    testcase.assertEqual(_board_pick_count(session), 0)
    testcase.assertNotIn(SIMULATOR_RESUME_IDENTITY_KEY, session)
    stamp = session.get(SIMULATOR_BOARD_OWNERSHIP_KEY)
    if isinstance(stamp, dict):
        testcase.assertNotEqual(stamp.get("simulator_owner_external_id"), "daniel")


class FakeAuthUser:
    def __init__(self, *, user_id: str, email: str) -> None:
        self.id = user_id
        self.email = email


class SimulatorResumeAccountIsolationTests(unittest.TestCase):
    def test_daniel_simulator_resume_scoped_to_account(self) -> None:
        session = _daniel_session()
        ctx = get_draft_return_context(session)
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.get("kind"), "simulator")
        self.assertEqual(ctx.get("user_team"), "Donny")
        frozen = session.get(SIMULATOR_RESUME_IDENTITY_KEY)
        self.assertIsInstance(frozen, dict)
        assert isinstance(frozen, dict)
        self.assertEqual(frozen.get("external_id"), "daniel")
        self.assertEqual(frozen.get("workspace_id"), "daniel")
        self.assertEqual(frozen.get("user_team"), "Donny")
        self.assertTrue(str(frozen.get("board_fingerprint") or "").startswith("sim:"))
        stamp = session.get(SIMULATOR_BOARD_OWNERSHIP_KEY)
        self.assertIsInstance(stamp, dict)
        assert isinstance(stamp, dict)
        self.assertEqual(stamp.get("simulator_owner_external_id"), "daniel")

    def test_sign_out_clears_private_simulator_runtime(self) -> None:
        session = _daniel_session()
        get_draft_return_context(session)
        self.assertIn(SIMULATOR_RESUME_IDENTITY_KEY, session)
        _clear_auth_session(session)
        self.assertNotIn(SIMULATOR_RESUME_IDENTITY_KEY, session)
        self.assertNotIn("room_your_team", session)
        self.assertNotIn("draft_shared_settings", session)
        self.assertEqual(_board_pick_count(session), 0)
        diag = collect_simulator_resume_diagnostics(session)
        self.assertEqual(diag.get("stale_resume_discarded_reason"), "auth_sign_out")

    def test_same_browser_daniel_to_coakley_clears_donny_resume(self) -> None:
        session = _daniel_session()
        first = get_draft_return_context(session)
        self.assertEqual((first or {}).get("user_team"), "Donny")

        # Sign out Daniel — private simulator must not survive.
        _clear_auth_session(session)
        self.assertIsNone(get_draft_return_context(session))

        # Sign in Coakley11 on the same browser session object.
        coakley = FakeAuthUser(user_id="user:coakley11", email="coakley11@aol.com")
        with mock.patch("suite_auth._sync_auth_account_identity", return_value="user:coakley11"):
            with mock.patch("suite_auth.enforce_workspace_ownership"):
                with mock.patch("suite_auth.is_authenticated", return_value=True):
                    _persist_auth_session(
                        session,
                        user=coakley,
                        tokens={"access_token": "t", "refresh_token": "r"},
                        email_fallback="coakley11@aol.com",
                    )
        session["_suite_active_workspace_id"] = "coakley11"
        session["_suite_owned_workspace_id"] = "coakley11"
        session[AUTH_EXTERNAL_ID_KEY] = "coakley11"

        # Even if stale Donny keys somehow remain, ownership mismatch must wipe them.
        session["draft_room_table"] = _sim_board(team="Donny", picks=12)
        session["room_your_team"] = "Donny"
        session[SIMULATOR_RESUME_IDENTITY_KEY] = {
            "kind": "simulator",
            "user_team": "Donny",
            "auth_user_id": "user:daniel",
            "external_id": "daniel",
            "workspace_id": "daniel",
            "board_fingerprint": "sim:12:deadbeef",
        }
        ctx = get_draft_return_context(session)
        _assert_no_donny_simulator_card(self, session, ctx)
        self.assertIsNone(ctx)
        diag = collect_simulator_resume_diagnostics(session)
        self.assertTrue(
            str(diag.get("stale_resume_discarded_reason") or "").startswith("mismatch_")
            or str(diag.get("simulator_board_rejected_reason") or "")
            in {"legacy_or_foreign_board", "legacy_unowned_board_rejected"}
            or str(diag.get("stale_resume_discarded_reason") or "")
            in {
                "legacy_or_foreign_board",
                "legacy_unowned_board_rejected",
            }
        )
        self.assertNotEqual(diag.get("resume_team"), "Donny")

    def test_existing_coakley_session_rejects_unowned_stale_board_without_freeze(self) -> None:
        """Signed-in Coakley11 after deploy: stale 20-pick board, no frozen resume → no re-stamp."""
        session = _coakley_session()
        session["draft_room_table"] = _sim_board(team="Donny", picks=20)
        session["draft_room_state"] = {"mode": "draft_room_simulator", "pick_count": 20}
        session["room_your_team"] = "Donny"
        session["page_filter_state"] = {
            "Draft Room Simulator": {
                "draft_room_table": _sim_board(team="Donny", picks=20).to_dict("list"),
                "room_your_team": "Donny",
            }
        }
        # No SIMULATOR_RESUME_IDENTITY_KEY, no ownership stamp.
        scrub = scrub_simulator_runtime_for_current_account(session, reason="prepare_baseball_workspace")
        self.assertTrue(scrub.get("cleared"))
        self.assertFalse(scrub.get("verified"))
        self.assertEqual(scrub.get("reason"), "legacy_or_foreign_board")
        self.assertEqual(_board_pick_count(session), 0)
        self.assertNotIn(SIMULATOR_BOARD_OWNERSHIP_KEY, session)

        ctx = get_draft_return_context(session)
        self.assertIsNone(ctx)
        _assert_no_donny_simulator_card(self, session, ctx)
        diag = collect_simulator_resume_diagnostics(session)
        self.assertFalse(diag.get("simulator_board_owner_verified"))
        self.assertIn(
            str(diag.get("simulator_board_rejected_reason") or ""),
            {"legacy_or_foreign_board", "legacy_unowned_board_rejected"},
        )
        self.assertNotEqual(diag.get("sidebar_source_selected"), "draft_simulator")
        self.assertNotEqual(diag.get("resume_team"), "Donny")

    def test_unowned_board_is_not_stamped_as_coakley_on_sidebar(self) -> None:
        session = _coakley_session()
        session["draft_room_table"] = _sim_board(team="Donny", picks=20)
        session["room_your_team"] = "Donny"
        get_draft_return_context(session)
        self.assertNotIn(SIMULATOR_BOARD_OWNERSHIP_KEY, session)
        self.assertEqual(_board_pick_count(session), 0)

    def test_joined_shared_live_draft_beats_private_simulator(self) -> None:
        session = {
            AUTH_USER_ID_KEY: "user:coakley11",
            AUTH_EXTERNAL_ID_KEY: "coakley11",
            "_suite_active_workspace_id": "coakley11",
            "_suite_owned_workspace_id": "coakley11",
            "room_your_team": "Donny",
            "draft_room_table": _sim_board(team="Donny", picks=12),
            SIMULATOR_RESUME_IDENTITY_KEY: {
                "kind": "simulator",
                "user_team": "Donny",
                "auth_user_id": "user:daniel",
                "external_id": "daniel",
                "workspace_id": "daniel",
                "board_fingerprint": "sim:12:deadbeef",
            },
            "live_draft_room": {
                "draft_room_id": "room-robins",
                "status": "in_progress",
                "teams": ["Donny", "Team B"],
                "config": {
                    "league_name": "Robins Fantasy",
                    "your_team": "Team B",
                    "user_team": "Team B",
                    "projection_style": "Conservative",
                },
                "draft_board": [{"Pick": 1, "Team": "Donny", "Player": "A"}],
                "pick_order": ["Donny", "Team B"],
                "current_pick_index": 1,
            },
            "live_draft_setup_mode": "shared_multiplayer",
            "active_shared_draft_room_code": "ROBINS",
            "draft_room_participant_team": "Team B",
            "draft_room_participant_membership": {
                "ROBINS": {
                    "user:coakley11": {
                        "participant_id": "user:coakley11",
                        "assigned_team": "Team B",
                    }
                }
            },
        }
        with mock.patch("live_draft_state.has_active_live_draft", return_value=True):
            with mock.patch(
                "fantasy_workspace_team_identity.resolve_current_account_team_for_live_draft_and_league",
                return_value="Team B",
            ):
                with mock.patch(
                    "draft_room_participant_state.resolve_participant_id",
                    return_value="user:coakley11",
                ):
                    ctx = get_draft_return_context(session)
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.get("title"), "Return to Live Draft")
        self.assertEqual(ctx.get("user_team"), "Team B")
        self.assertNotEqual(ctx.get("kind"), "simulator")
        diag = collect_simulator_resume_diagnostics(session)
        self.assertEqual(diag.get("resume_source_kind"), "live_draft")
        self.assertEqual(diag.get("sidebar_source_selected"), "live_draft")
        self.assertEqual(diag.get("sidebar_priority_reason"), "draft_started")
        self.assertEqual(diag.get("shared_membership_team"), "Team B")

    def test_shared_membership_without_start_keeps_simulator(self) -> None:
        session = _coakley_session()
        session["draft_room_table"] = _sim_board(team="Team B", picks=20)
        session["room_your_team"] = "Team B"
        stamp_simulator_board_ownership(session, origin="programmatic_pick")
        session["live_draft_setup_mode"] = "shared_multiplayer"
        session["active_shared_draft_room_code"] = "TEAM02"
        session["draft_room_participant_team"] = "Team 2"
        session["draft_room_participant_membership"] = {
            "TEAM02": {
                "user:coakley11": {
                    "participant_id": "user:coakley11",
                    "assigned_team": "Team 2",
                }
            }
        }
        # No live_draft_room / not started — Simulator remains primary.
        with mock.patch(
            "draft_room_participant_state.resolve_participant_id",
            return_value="user:coakley11",
        ):
            with mock.patch(
                "live_draft_navigation._try_hydrate_shared_room",
                return_value=None,
            ):
                from live_draft_navigation import (
                    get_live_draft_lobby_return_context,
                    resolve_live_draft_activation_phase,
                )

                ctx = get_draft_return_context(session)
                lobby = get_live_draft_lobby_return_context(session)
                phase = resolve_live_draft_activation_phase(session)
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.get("kind"), "simulator")
        self.assertEqual(ctx.get("user_team"), "Team B")
        self.assertEqual(phase, "participant_team_claimed")
        self.assertIsNotNone(lobby)
        assert lobby is not None
        self.assertEqual(lobby.get("kind"), "live_lobby")
        self.assertEqual(lobby.get("user_team"), "Team 2")
        self.assertIsNone(lobby.get("pick_no"))
        self.assertIsNone(lobby.get("on_clock"))

    def test_foreign_board_cannot_rehydrate_from_page_filter_or_caches(self) -> None:
        session = _coakley_session()
        board = _sim_board(team="Donny", picks=20)
        session["draft_room_table"] = board
        session["draft_room_state"] = {"mode": "draft_room_simulator"}
        session["draft_room_board_editor_cache"] = board.copy()
        session["page_filter_state"] = {
            "Draft Room Simulator": {"draft_room_table": board.to_dict("list")}
        }
        session["_suite_full_session_cache"] = {
            "draft_room_table": board.to_dict("list"),
            "page_filter_state": {"Draft Room Simulator": {"room_your_team": "Donny"}},
        }
        clear_private_baseball_simulator_runtime(session, reason="legacy_or_foreign_board")
        self.assertEqual(_board_pick_count(session), 0)
        self.assertNotIn("draft_room_board_editor_cache", session)
        cache = session.get("_suite_full_session_cache") or {}
        self.assertNotIn("draft_room_table", cache)
        nested_pf = (cache.get("page_filter_state") or {}).get("Draft Room Simulator")
        self.assertTrue(nested_pf is None or not nested_pf)

        # Re-seed from every alias and re-run prepare scrub + sidebar — must reject again.
        session["draft_room_table"] = board.copy()
        session["draft_room_state"] = {"mode": "draft_room_simulator"}
        session["page_filter_state"] = {
            "Draft Room Simulator": {"draft_room_table": board.to_dict("list")}
        }
        scrub_simulator_runtime_for_current_account(
            session, reason="prepare_baseball_workspace", force=True
        )
        ctx = get_draft_return_context(session)
        self.assertIsNone(ctx)
        _assert_no_donny_simulator_card(self, session, ctx)

    def test_clear_private_runtime_preserves_live_draft_room(self) -> None:
        session = _daniel_session()
        session["live_draft_room"] = {
            "draft_room_id": "shared-1",
            "status": "in_progress",
            "teams": ["Donny", "Team B"],
            "config": {"your_team": "Team B"},
        }
        session["active_shared_draft_room_code"] = "ABC123"
        session["draft_room_participant_team"] = "Team B"
        clear_private_baseball_simulator_runtime(session, reason="workspace_changed")
        self.assertIn("live_draft_room", session)
        self.assertEqual(session.get("active_shared_draft_room_code"), "ABC123")
        self.assertEqual(session.get("draft_room_participant_team"), "Team B")
        self.assertEqual(_board_pick_count(session), 0)
        self.assertNotIn(SIMULATOR_RESUME_IDENTITY_KEY, session)

    def test_stamp_only_on_deliberate_local_edit(self) -> None:
        session = _coakley_session()
        session["draft_room_table"] = _sim_board(team="Team 2", picks=3)
        stamp = stamp_simulator_board_ownership(session, origin="programmatic_pick")
        self.assertIsNotNone(stamp)
        assert stamp is not None
        self.assertEqual(stamp.get("simulator_owner_external_id"), "coakley11")
        self.assertEqual(stamp.get("simulator_owner_workspace_id"), "coakley11")
        ctx = get_draft_return_context(session)
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.get("kind"), "simulator")
        self.assertNotEqual(ctx.get("user_team"), "Donny")


if __name__ == "__main__":
    unittest.main()
