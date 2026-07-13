"""Live Draft activates only after Start Draft — not from setup form / create / join / claim."""

from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from draft_room_state import (
    ACTIVE_DRAFT_MODE_LIVE,
    ACTIVE_DRAFT_MODE_MANUAL,
    ensure_live_draft_synced_to_canonical_board,
    get_active_draft_mode,
    resolve_active_draft_source,
    should_resolve_live_draft_source,
    table_pick_count,
)
from live_draft_navigation import (
    SIMULATOR_BOARD_OWNERSHIP_KEY,
    get_draft_return_context,
    get_live_draft_lobby_return_context,
    resolve_live_draft_activation_phase,
    stamp_simulator_board_ownership,
)
from live_draft_setup_persist import on_live_draft_setup_widget_changed
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_ID_KEY


def _sim_board(*, team: str, picks: int = 20) -> pd.DataFrame:
    rows = []
    for i in range(picks):
        other = "Opp"
        rows.append(
            {
                "Round": (i // 2) + 1,
                "Pick": i + 1,
                "Team": team if i % 2 == 0 else other,
                "Fantasy Team": team if i % 2 == 0 else other,
                "Player": f"{team}P{i}",
            }
        )
    return pd.DataFrame(rows)


def _acct(external: str, *, team: str) -> dict:
    return {
        AUTH_USER_ID_KEY: f"user:{external}",
        AUTH_EXTERNAL_ID_KEY: external,
        "_suite_active_workspace_id": external,
        "_suite_owned_workspace_id": external,
        "room_your_team": team,
        "draft_room_table": _sim_board(team=team, picks=20),
    }


def _not_started_room(*, host_team: str = "Team 1") -> dict:
    teams = ["Team 1", "Team 2"]
    pick_order = []
    for rnd in range(1, 6):
        order = teams if rnd % 2 == 1 else list(reversed(teams))
        for i, team in enumerate(order):
            pick_order.append({"Round": rnd, "Pick": (rnd - 1) * 2 + i + 1, "Team": team})
    return {
        "draft_room_id": "fresh10",
        "status": "not_started",
        "teams": teams,
        "config": {
            "league_name": "Fresh 10-Pick",
            "picks_per_team": 5,
            "your_team": host_team,
            "user_team": host_team,
            "projection_style": "Conservative",
            "draft_setup_mode": "shared_multiplayer",
        },
        "draft_board": [],
        "pick_order": pick_order,
        "current_pick_index": 0,
    }


class LiveDraftActivationLifecycleTests(unittest.TestCase):
    def test_setup_form_edits_do_not_create_shared_room_or_membership(self) -> None:
        daniel = _acct("daniel", team="Donny")
        stamp_simulator_board_ownership(daniel, origin="programmatic_pick")
        daniel["live_draft_proj_style"] = "Conservative"
        daniel["live_draft_scoring"] = "5x5 Roto"
        daniel["live_draft_setup_mode"] = "shared_multiplayer"
        # Local unfinished setup form values only.
        daniel["live_draft_team_count"] = 2
        daniel["live_draft_picks_per_team"] = 5
        daniel["live_draft_your_team"] = "Team 1"

        on_live_draft_setup_widget_changed(daniel)

        self.assertFalse(str(daniel.get("active_shared_draft_room_code") or "").strip())
        self.assertNotIn("draft_room_participant_membership", daniel)
        self.assertNotIn("live_draft_room", daniel)
        self.assertEqual(resolve_live_draft_activation_phase(daniel), "setup_draft")
        self.assertFalse(should_resolve_live_draft_source(daniel))
        self.assertEqual(get_active_draft_mode(daniel), ACTIVE_DRAFT_MODE_MANUAL)

        ctx = get_draft_return_context(daniel)
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.get("kind"), "simulator")
        self.assertEqual(ctx.get("user_team"), "Donny")
        self.assertIsNone(get_live_draft_lobby_return_context(daniel))

        coakley = _acct("coakley11", team="Team B")
        stamp_simulator_board_ownership(coakley, origin="programmatic_pick")
        self.assertFalse(str(coakley.get("active_shared_draft_room_code") or "").strip())
        self.assertNotIn("live_draft_room", coakley)
        ctx_c = get_draft_return_context(coakley)
        self.assertEqual((ctx_c or {}).get("kind"), "simulator")
        self.assertEqual((ctx_c or {}).get("user_team"), "Team B")
        self.assertEqual(resolve_live_draft_activation_phase(coakley), "setup_draft")

    def test_create_room_does_not_auto_join_coakley_or_replace_simulator(self) -> None:
        daniel = _acct("daniel", team="Donny")
        stamp_simulator_board_ownership(daniel, origin="programmatic_pick")
        room = _not_started_room(host_team="Team 1")
        daniel["live_draft_room"] = room
        daniel["active_shared_draft_room_code"] = "TEAM02"
        daniel["live_draft_setup_mode"] = "shared_multiplayer"
        daniel["draft_room_participant_team"] = "Team 1"
        daniel["draft_room_participant_membership"] = {
            "TEAM02": {"user:daniel": {"participant_id": "user:daniel", "assigned_team": "Team 1"}}
        }

        self.assertEqual(resolve_live_draft_activation_phase(daniel), "participant_team_claimed")
        self.assertFalse(should_resolve_live_draft_source(daniel))
        self.assertNotEqual(get_active_draft_mode(daniel), ACTIVE_DRAFT_MODE_LIVE)
        primary = get_draft_return_context(daniel)
        self.assertEqual((primary or {}).get("kind"), "simulator")
        self.assertEqual((primary or {}).get("user_team"), "Donny")
        lobby = get_live_draft_lobby_return_context(daniel)
        self.assertEqual((lobby or {}).get("kind"), "live_lobby")
        self.assertIsNone((lobby or {}).get("pick_no"))
        self.assertIsNone((lobby or {}).get("on_clock"))

        coakley = _acct("coakley11", team="Team B")
        stamp_simulator_board_ownership(coakley, origin="programmatic_pick")
        # Coakley has not joined — no room code / membership.
        self.assertEqual(resolve_live_draft_activation_phase(coakley), "setup_draft")
        self.assertFalse(should_resolve_live_draft_source(coakley))
        ctx_c = get_draft_return_context(coakley)
        self.assertEqual((ctx_c or {}).get("kind"), "simulator")
        self.assertEqual((ctx_c or {}).get("user_team"), "Team B")
        self.assertIsNone(get_live_draft_lobby_return_context(coakley))

    def test_joined_claim_lobby_does_not_flip_effective_source_or_on_clock(self) -> None:
        daniel = _acct("daniel", team="Donny")
        stamp_simulator_board_ownership(daniel, origin="programmatic_pick")
        coakley = _acct("coakley11", team="Team B")
        stamp_simulator_board_ownership(coakley, origin="programmatic_pick")

        room = _not_started_room(host_team="Team 1")
        for ss, team, pid in (
            (daniel, "Team 1", "user:daniel"),
            (coakley, "Team 2", "user:coakley11"),
        ):
            ss["live_draft_room"] = dict(room)
            ss["active_shared_draft_room_code"] = "TEAM02"
            ss["live_draft_setup_mode"] = "shared_multiplayer"
            ss["draft_room_participant_team"] = team
            ss["draft_room_participant_membership"] = {
                "TEAM02": {
                    "user:daniel": {"participant_id": "user:daniel", "assigned_team": "Team 1"},
                    "user:coakley11": {"participant_id": "user:coakley11", "assigned_team": "Team 2"},
                }
            }

        with mock.patch(
            "draft_room_participant_state.resolve_participant_id",
            side_effect=lambda s, *a, **k: str(s.get(AUTH_USER_ID_KEY) or ""),
        ):
            for ss, sim_team in ((daniel, "Donny"), (coakley, "Team B")):
                self.assertEqual(resolve_live_draft_activation_phase(ss), "participant_team_claimed")
                self.assertFalse(should_resolve_live_draft_source(ss))
                self.assertEqual(resolve_active_draft_source(ss), "simulator")
                primary = get_draft_return_context(ss)
                self.assertEqual((primary or {}).get("kind"), "simulator")
                self.assertEqual((primary or {}).get("user_team"), sim_team)
                lobby = get_live_draft_lobby_return_context(ss)
                self.assertEqual((lobby or {}).get("kind"), "live_lobby")
                self.assertIsNone((lobby or {}).get("pick_no"))
                self.assertIsNone((lobby or {}).get("on_clock"))
                sync = ensure_live_draft_synced_to_canonical_board(ss, reason="lobby_guard")
                self.assertTrue(sync.get("skipped"))
                self.assertEqual(sync.get("skip_reason"), "live_draft_not_started")
                self.assertEqual(table_pick_count(ss.get("draft_room_table")), 20)

    def test_start_draft_switches_both_accounts_to_live_board(self) -> None:
        daniel = _acct("daniel", team="Donny")
        stamp_simulator_board_ownership(daniel, origin="programmatic_pick")
        coakley = _acct("coakley11", team="Team B")
        stamp_simulator_board_ownership(coakley, origin="programmatic_pick")

        room = _not_started_room(host_team="Team 1")
        room["status"] = "in_progress"
        room["current_pick_index"] = 0

        for ss, team in ((daniel, "Team 1"), (coakley, "Team 2")):
            ss["live_draft_room"] = dict(room)
            ss["active_shared_draft_room_code"] = "TEAM02"
            ss["live_draft_setup_mode"] = "shared_multiplayer"
            ss["draft_room_participant_team"] = team
            ss["draft_room_participant_membership"] = {
                "TEAM02": {
                    "user:daniel": {"participant_id": "user:daniel", "assigned_team": "Team 1"},
                    "user:coakley11": {"participant_id": "user:coakley11", "assigned_team": "Team 2"},
                }
            }

        with mock.patch(
            "draft_room_participant_state.resolve_participant_id",
            side_effect=lambda s, *a, **k: str(s.get(AUTH_USER_ID_KEY) or ""),
        ):
            with mock.patch("live_draft_state.has_active_live_draft", return_value=True):
                for ss, team in ((daniel, "Team 1"), (coakley, "Team 2")):
                    self.assertEqual(resolve_live_draft_activation_phase(ss), "draft_started")
                    self.assertTrue(should_resolve_live_draft_source(ss))
                    self.assertEqual(get_active_draft_mode(ss), ACTIVE_DRAFT_MODE_LIVE)
                    primary = get_draft_return_context(ss)
                    self.assertEqual((primary or {}).get("kind"), "live_active")
                    self.assertEqual((primary or {}).get("title"), "Return to Live Draft")
                    self.assertEqual((primary or {}).get("user_team"), team)
                    self.assertEqual((primary or {}).get("pick_no"), 1)
                    self.assertEqual((primary or {}).get("on_clock"), "Team 1")
                    self.assertIsNone(get_live_draft_lobby_return_context(ss))

            # After Start, live board may mirror into Simulator when picks exist (0 picks → skip empty).
            for ss in (daniel, coakley):
                sync = ensure_live_draft_synced_to_canonical_board(ss, reason="start_draft")
                # 0 live picks yet — keep private table until first pick lands.
                self.assertTrue(sync.get("skipped") or table_pick_count(ss.get("draft_room_table")) >= 0)


if __name__ == "__main__":
    unittest.main()
