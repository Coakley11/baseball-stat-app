"""Manual Draft Player button must always paint (enabled or disabled)."""

from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from draft_ui import render_live_manual_draft_panel


class _Btn:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, label: str, **kwargs):
        self.calls.append({"label": label, **kwargs})
        return False


class _St:
    def __init__(self) -> None:
        self.button = _Btn()
        self.captions: list[str] = []
        self.infos: list[str] = []

    def subheader(self, *_a, **_k) -> None:
        pass

    def info(self, msg: str) -> None:
        self.infos.append(str(msg))

    def warning(self, *_a, **_k) -> None:
        pass

    def caption(self, msg: str) -> None:
        self.captions.append(str(msg))

    def selectbox(self, *_a, **_k):
        opts = _k.get("options") or (_a[1] if len(_a) > 1 else [])
        return opts[0] if opts else ""

    def markdown(self, *_a, **_k) -> None:
        pass

    def expander(self, *_a, **_k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def text(self, *_a, **_k) -> None:
        pass


class ManualDraftButtonVisibleTests(unittest.TestCase):
    def test_waiting_turn_still_shows_draft_player(self) -> None:
        room = {
            "status": "in_progress",
            "current_pick_index": 0,
            "teams": ["Team A", "Team B"],
            "pick_order": [
                {"Pick": 1, "Round": 1, "Team": "Team A"},
                {"Pick": 2, "Round": 1, "Team": "Team B"},
            ],
            "draft_board": [],
            "drafted_player_ids": [],
            "rosters": {"Team A": [], "Team B": []},
            "pool": pd.DataFrame(
                [{"playerID": "p1", "fullName": "Player One", "Primary Position": "OF"}]
            ),
            "config": {"your_team": "Team B", "num_teams": 2, "picks_per_team": 1},
        }
        session = {
            "draft_room_participant_team": "Team B",
            "active_shared_draft_room_code": "ABC123",
            "live_draft_room": room,
        }
        st = _St()
        with mock.patch(
            "draft_actions.resolve_manual_draft_panel_gate",
            return_value={
                "should_render": False,
                "is_my_turn": False,
                "on_clock_team": "Team A",
                "draft_status": "in_progress",
                "disable_reason": "Not your turn",
            },
        ), mock.patch("draft_ui.record_live_draft_ui_diagnostics"), mock.patch(
            "draft_ui.render_live_manual_draft_diagnostics"
        ):
            render_live_manual_draft_panel(st, session, room, user_team="Team B", multiplayer=True)
        labels = [c["label"] for c in st.button.calls]
        self.assertIn("Draft Player", labels)
        disabled = [c for c in st.button.calls if c["label"] == "Draft Player"]
        self.assertTrue(all(c.get("disabled") for c in disabled))


if __name__ == "__main__":
    unittest.main()
