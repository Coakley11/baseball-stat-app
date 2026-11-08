"""Lineup & Trades drag-and-drop snapped back to the bench (owner review, 2026-11-08).

Every move goes through the write-identity check (signed in, owns this team). When that check failed, the
board was still drawn as editable, so each drop was refused and the photo returned to the bench. Now:
* the board is read-only, with the reason above it, when this account can't change the lineup;
* a non-drag "Move a player" control places players with the same validated move and save path.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

import fantasy_weekly_lineup_ui as ui
from fantasy_league_context import get_active_league_context, save_simulator_league_context, upsert_league_context
from fantasy_lineup_interactive_board import BENCH_ZONE

SLOTS = [("SS", "SS"), ("OF", "OF 1")]


def _roster() -> pd.DataFrame:
    return pd.DataFrame([
        {"Team": "Daniel", "Player": "Aaron Judge", "Primary Position": "OF", "player_id": "judge1", "HR": 30},
        {"Team": "Daniel", "Player": "Francisco Lindor", "Primary Position": "SS", "player_id": "lindor1", "HR": 20},
    ])


class MoveTargetTests(unittest.TestCase):
    def test_only_eligible_slots_are_offered(self) -> None:
        roster = _roster()
        self.assertEqual([t for t, _ in ui.move_targets({}, SLOTS, "Francisco Lindor", roster)], ["SS"])
        self.assertEqual([t for t, _ in ui.move_targets({}, SLOTS, "Aaron Judge", roster)], ["OF"])

    def test_a_starter_can_go_to_the_bench_and_a_taken_slot_is_a_swap(self) -> None:
        roster = pd.concat([_roster(), pd.DataFrame([{"Team": "Daniel", "Player": "Trea Turner",
                                                      "Primary Position": "SS", "player_id": "turner1"}])])
        targets = dict(ui.move_targets({"SS": "Francisco Lindor"}, SLOTS, "Trea Turner", roster))
        self.assertEqual(targets["SS"], "SS (swap with Francisco Lindor)")
        self.assertIn(BENCH_ZONE, dict(ui.move_targets({"SS": "Francisco Lindor"}, SLOTS, "Francisco Lindor", roster)))
        self.assertNotIn(BENCH_ZONE, targets)  # already on the bench


def _page_session() -> dict:
    session: dict = {}
    board = pd.DataFrame([
        {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1, "Primary Position": "OF"},
        {"Team": "Daniel", "Player": "Francisco Lindor", "Pick": 2, "Primary Position": "SS"},
    ])
    save_simulator_league_context(session, board, my_team_name="Daniel")
    from fantasy_league_lineup_format import CONFIG_SOURCE_SIMULATOR, apply_lineup_format_to_context

    context = apply_lineup_format_to_context(get_active_league_context(session), lineup_slots=["SS", "OF"],
                                             roster_capacity=2, configured_by="daniel",
                                             configuration_source=CONFIG_SOURCE_SIMULATOR)
    upsert_league_context(session, context)
    return session


def _st(selects: dict | None = None, pressed: str = "") -> MagicMock:
    st = MagicMock()
    st.html = MagicMock()
    st.columns.side_effect = lambda n, **kw: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
    selects = selects or {}

    def _selectbox(label, options, *a, **kw):
        key = str(kw.get("key", ""))
        for prefix, value in selects.items():
            if key.startswith(prefix):
                return value
        return list(options)[0] if options else None

    st.selectbox.side_effect = _selectbox
    st.button.side_effect = lambda *a, **kw: bool(pressed) and str(kw.get("key", "")).startswith(pressed)
    st.expander.return_value.__enter__ = lambda s: s
    st.expander.return_value.__exit__ = lambda s, *a: False
    return st


class PageTests(unittest.TestCase):
    def test_a_refused_identity_makes_the_board_read_only_with_the_reason(self) -> None:
        session, st = _page_session(), _st()
        with patch("fantasy_weekly_lineup_ui.render_interactive_lineup_board", return_value=None), \
                patch("fantasy_weekly_lineup_ui._lineup_write_check",
                      return_value=(False, "Your account does not own a team in this league.")), \
                patch("fantasy_weekly_lineup_ui.build_interactive_board_payload", wraps=ui.build_interactive_board_payload) as build:
            ui.render_weekly_lineup_section(st, session, team_roster=_roster(), lineup_team="Daniel")
        self.assertFalse(build.call_args.kwargs["editable"])
        warnings = " ".join(str(c.args[0]) for c in st.warning.call_args_list)
        self.assertIn("does not own a team", warnings)
        self.assertIn("read-only", warnings)
        self.assertFalse(any("lineup_move_player_" in str(c.kwargs.get("key", "")) for c in st.selectbox.call_args_list))

    def test_an_allowed_account_gets_an_editable_board_and_the_move_control(self) -> None:
        session, st = _page_session(), _st()
        with patch("fantasy_weekly_lineup_ui.render_interactive_lineup_board", return_value=None), \
                patch("fantasy_weekly_lineup_ui._lineup_write_check", return_value=(True, "")), \
                patch("fantasy_weekly_lineup_ui.build_interactive_board_payload", wraps=ui.build_interactive_board_payload) as build:
            ui.render_weekly_lineup_section(st, session, team_roster=_roster(), lineup_team="Daniel")
        self.assertTrue(build.call_args.kwargs["editable"])
        self.assertTrue(any("lineup_move_player_" in str(c.kwargs.get("key", "")) for c in st.selectbox.call_args_list))

    def test_move_a_player_places_and_saves_through_the_drop_path(self) -> None:
        session = _page_session()
        st = _st({"lineup_move_player_": "Francisco Lindor", "lineup_move_target_": "SS"}, pressed="lineup_move_btn_")
        with patch("fantasy_weekly_lineup_ui.render_interactive_lineup_board", return_value=None), \
                patch("fantasy_weekly_lineup_ui._lineup_write_check", return_value=(True, "")), \
                patch("fantasy_weekly_lineup_ui.persist_weekly_lineup_draft", return_value={"ok": True}) as persist, \
                patch("fantasy_weekly_lineup_ui.get_saved_weekly_lineup",
                      side_effect=lambda *a, **k: {"assignments": {"SS": "Francisco Lindor"}}):
            ui.render_weekly_lineup_section(st, session, team_roster=_roster(), lineup_team="Daniel")
        self.assertTrue(persist.called)
        saved = persist.call_args.kwargs["assignments"]
        self.assertEqual({k: v for k, v in saved.items() if v}, {"SS": "Francisco Lindor"})
        st.rerun.assert_called()


if __name__ == "__main__":
    unittest.main()
