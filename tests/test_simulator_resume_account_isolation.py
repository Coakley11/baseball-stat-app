"""Same-browser account transition must not leak private Draft Simulator resume."""

from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from live_draft_navigation import (
    SIMULATOR_RESUME_IDENTITY_KEY,
    clear_private_baseball_simulator_runtime,
    collect_simulator_resume_diagnostics,
    get_draft_return_context,
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

    def test_sign_out_clears_private_simulator_runtime(self) -> None:
        session = _daniel_session()
        get_draft_return_context(session)
        self.assertIn(SIMULATOR_RESUME_IDENTITY_KEY, session)
        _clear_auth_session(session)
        self.assertNotIn("draft_room_table", session)
        self.assertNotIn(SIMULATOR_RESUME_IDENTITY_KEY, session)
        self.assertNotIn("room_your_team", session)
        self.assertNotIn("draft_shared_settings", session)
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
        self.assertIsNone(ctx)
        self.assertNotIn(SIMULATOR_RESUME_IDENTITY_KEY, session)
        self.assertNotEqual(session.get("room_your_team"), "Donny")
        leftover = session.get("draft_room_table")
        if leftover is not None and hasattr(leftover, "empty") and not leftover.empty:
            players = []
            if "Player" in leftover.columns:
                players = [str(p).strip() for p in leftover["Player"].tolist() if str(p).strip()]
            self.assertEqual(players, [])
        diag = collect_simulator_resume_diagnostics(session)
        self.assertTrue(str(diag.get("stale_resume_discarded_reason") or "").startswith("mismatch_"))
        self.assertNotEqual(diag.get("resume_team"), "Donny")

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
        }
        with mock.patch("live_draft_state.has_active_live_draft", return_value=True):
            with mock.patch(
                "fantasy_workspace_team_identity.resolve_current_account_team_for_live_draft_and_league",
                return_value="Team B",
            ):
                ctx = get_draft_return_context(session)
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.get("title"), "Return to Live Draft")
        self.assertEqual(ctx.get("user_team"), "Team B")
        self.assertNotEqual(ctx.get("kind"), "simulator")
        diag = collect_simulator_resume_diagnostics(session)
        self.assertEqual(diag.get("resume_source_kind"), "live_draft")
        self.assertEqual(diag.get("active_shared_room_team"), "Team B")

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
        self.assertNotIn("draft_room_table", session)
        self.assertNotIn(SIMULATOR_RESUME_IDENTITY_KEY, session)


if __name__ == "__main__":
    unittest.main()
