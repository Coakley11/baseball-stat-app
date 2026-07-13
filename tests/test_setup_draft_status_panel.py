"""Status panel must not show Pick 1 / On Clock during Live Draft setup_draft."""

from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from draft_actions import draft_status_summary, live_pick_clock_may_display
from draft_ui import render_draft_sidebar_status
from live_draft_navigation import resolve_live_draft_activation_phase
from live_draft_setup_ui import render_draft_status_summary_card
from live_draft_state import analyze_live_draft_progress
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_ID_KEY


class _FakeSidebar:
    def __init__(self) -> None:
        self.captions: list[str] = []
        self.markdowns: list[str] = []

    def caption(self, text: str) -> None:
        self.captions.append(str(text))

    def markdown(self, text: str, **_kwargs) -> None:
        self.markdowns.append(str(text))


class _FakeStreamlit:
    def __init__(self) -> None:
        self.sidebar = _FakeSidebar()
        self.markdowns: list[str] = []
        self._border = False

    def caption(self, text: str) -> None:
        self.sidebar.captions.append(str(text))

    def markdown(self, text: str, **_kwargs) -> None:
        self.markdowns.append(str(text))

    def container(self, border: bool = False):
        self._border = border
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _robins_board() -> pd.DataFrame:
    rows = []
    for i in range(20):
        team = "Donny" if i % 2 == 0 else "Team B"
        rows.append(
            {
                "Round": (i // 2) + 1,
                "Pick": i + 1,
                "Team": team,
                "Fantasy Team": team,
                "Player": f"R{i}",
            }
        )
    return pd.DataFrame(rows)


def _setup_room_not_started() -> dict:
    teams = ["Team 1", "Team 2"]
    pick_order = []
    for rnd in range(1, 6):
        order = teams if rnd % 2 == 1 else list(reversed(teams))
        for i, team in enumerate(order):
            pick_order.append({"Round": rnd, "Pick": (rnd - 1) * 2 + i + 1, "Team": team})
    return {
        "draft_room_id": "setup-local",
        "status": "not_started",
        "teams": teams,
        "config": {
            "picks_per_team": 5,
            "your_team": "Team 1",
            "projection_style": "Conservative",
        },
        "draft_board": [],
        "pick_order": pick_order,
        "current_pick_index": 0,
    }


class SetupDraftStatusPanelTests(unittest.TestCase):
    def test_analyze_not_started_has_no_pick_or_clock(self) -> None:
        progress = analyze_live_draft_progress(_setup_room_not_started())
        self.assertIsNone(progress.get("current_pick"))
        self.assertIsNone(progress.get("on_clock_team"))
        self.assertEqual(progress.get("draft_complete_reason"), "not_started")

    def test_setup_form_only_sidebar_status_panel_hides_pick_and_clock(self) -> None:
        """Daniel opened Live Draft and edited setup — no Create Room / Start Draft."""
        session = {
            AUTH_USER_ID_KEY: "user:daniel",
            AUTH_EXTERNAL_ID_KEY: "daniel",
            "_suite_active_workspace_id": "daniel",
            "_suite_owned_workspace_id": "daniel",
            "room_your_team": "Donny",
            "draft_room_table": _robins_board(),
            "live_draft_setup_mode": "shared_multiplayer",
            "live_draft_proj_style": "Conservative",
            "live_draft_team_count": 2,
            "live_draft_picks_per_team": 5,
            "live_draft_your_team": "Team 1",
            # Local unfinished setup may already materialize a not_started room object.
            "live_draft_room": _setup_room_not_started(),
        }
        self.assertEqual(resolve_live_draft_activation_phase(session), "shared_room_created")
        self.assertFalse(live_pick_clock_may_display(session))

        summary = draft_status_summary(session)
        self.assertEqual(summary.get("active_draft_source"), "simulator")
        self.assertIsNone(summary.get("pick"))
        self.assertIsNone(summary.get("current_pick"))
        self.assertIsNone(summary.get("on_clock_team"))
        self.assertIsNone(summary.get("timer_seconds"))
        self.assertFalse(summary.get("has_active_draft"))

        st = _FakeStreamlit()
        with mock.patch("draft_ui.render_draft_sidebar_timer"):
            out = render_draft_sidebar_status(st, session)
        self.assertIsNone(out.get("pick"))
        self.assertIsNone(out.get("on_clock_team"))
        joined = " ".join(st.sidebar.markdowns + st.sidebar.captions)
        self.assertNotIn("Pick 1", joined)
        self.assertNotIn("On Clock", joined)
        self.assertNotIn("Team 1", joined)

        # Page status card for lobby also suppresses pick/clock.
        page = _FakeStreamlit()
        with mock.patch("live_draft_setup_ui.shared_room_code", return_value=""):
            with mock.patch("live_draft_setup_ui._is_room_host", return_value=True):
                with mock.patch("live_draft_setup_ui.count_joined_teams", return_value=(0, 2)):
                    with mock.patch("live_draft_setup_ui.team_claim_rows", return_value=[]):
                        render_draft_status_summary_card(
                            page,
                            session,
                            session["live_draft_room"],
                            on_clock_team="Team 1",
                            pick_label="Pick 1 / 10",
                        )
        body = " ".join(page.markdowns)
        self.assertNotIn("Current Pick", body)
        self.assertNotIn("On the Clock", body)

    def test_pure_setup_draft_phase_without_room_also_hides_panel(self) -> None:
        session = {
            AUTH_USER_ID_KEY: "user:daniel",
            AUTH_EXTERNAL_ID_KEY: "daniel",
            "_suite_active_workspace_id": "daniel",
            "_suite_owned_workspace_id": "daniel",
            "room_your_team": "Donny",
            "draft_room_table": _robins_board(),
            "live_draft_setup_mode": "shared_multiplayer",
        }
        self.assertEqual(resolve_live_draft_activation_phase(session), "setup_draft")
        self.assertFalse(live_pick_clock_may_display(session))
        summary = draft_status_summary(session)
        self.assertEqual(summary.get("active_draft_source"), "simulator")
        self.assertIsNone(summary.get("pick"))
        self.assertIsNone(summary.get("on_clock_team"))
        st = _FakeStreamlit()
        render_draft_sidebar_status(st, session)
        joined = " ".join(st.sidebar.markdowns + st.sidebar.captions)
        self.assertNotIn("Pick ", joined)
        self.assertNotIn("On Clock", joined)

    def test_in_progress_still_shows_pick_one_team_one(self) -> None:
        room = _setup_room_not_started()
        room["status"] = "in_progress"
        session = {
            AUTH_USER_ID_KEY: "user:daniel",
            AUTH_EXTERNAL_ID_KEY: "daniel",
            "_suite_active_workspace_id": "daniel",
            "live_draft_room": room,
            "active_shared_draft_room_code": "TEAM02",
            "draft_room_participant_team": "Team 1",
            "draft_room_participant_membership": {
                "TEAM02": {"user:daniel": {"participant_id": "user:daniel", "assigned_team": "Team 1"}}
            },
            "draft_room_table": pd.DataFrame(),
        }
        self.assertTrue(live_pick_clock_may_display(session))
        progress = analyze_live_draft_progress(room)
        self.assertEqual(progress.get("current_pick"), 1)
        self.assertEqual(progress.get("on_clock_team"), "Team 1")
        with mock.patch("draft_room_state.resolve_active_draft_source", return_value="live"):
            with mock.patch("draft_room_state.is_live_draft_runtime_active", return_value=True):
                summary = draft_status_summary(session)
        self.assertEqual(summary.get("pick"), 1)
        self.assertEqual(summary.get("on_clock_team"), "Team 1")


if __name__ == "__main__":
    unittest.main()
