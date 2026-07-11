"""Tests for Fantasy Lineup roster board UI view models."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from fantasy_lineup_ui import (
    bench_player_cards,
    build_empty_slot_model,
    build_player_card_model,
    build_slot_cards,
    build_slot_key_labels,
    build_team_header_model,
    format_repeated_slot_label,
    inject_lineup_board_styles,
    initials_from_name,
    photo_html_for_player,
    render_bench_section_html,
    render_roster_board_html,
    render_slot_card_html,
    render_starting_lineup_board_html,
    roster_names_for_team,
    slot_key_labels_as_tuples,
)
from fantasy_weekly_lineup import (
    assignments_to_slot_player_map,
    save_weekly_lineup,
    validate_weekly_lineup,
)
from fantasy_weekly_lineup_dnd import assignments_from_sortable_containers, build_sortable_containers


def _roster_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Team": "Daniel",
                "Player": "Mookie Betts",
                "Primary Position": "OF",
                "HR": 18,
                "RBI": 55,
                "SB": 8,
                "OPS": 0.910,
                "player_id": "betts1",
            },
            {
                "Team": "Daniel",
                "Player": "Bench Hitter",
                "Primary Position": "1B",
                "HR": 5,
                "RBI": 20,
                "SB": 1,
                "OPS": 0.720,
                "player_id": "bench1",
            },
            {
                "Team": "Team 2",
                "Player": "Francisco Lindor",
                "Primary Position": "SS",
                "HR": 15,
                "RBI": 48,
                "SB": 12,
                "OPS": 0.820,
                "player_id": "lindor1",
            },
        ]
    )


class SlotLabelTests(unittest.TestCase):
    def test_repeated_of_slot_labels(self) -> None:
        labels = build_slot_key_labels(["C", "1B", "OF", "OF", "OF", "UTIL"])
        self.assertEqual([x.label for x in labels], ["Catcher", "First Base", "OF 1", "OF 2", "OF 3", "UTIL"])
        self.assertEqual([x.key for x in labels], ["C", "1B", "OF", "OF_2", "OF_3", "UTIL"])
        self.assertEqual(format_repeated_slot_label("OF", 2), "OF 2")

    def test_slot_key_labels_as_tuples(self) -> None:
        labels = build_slot_key_labels(["SS", "OF", "OF"])
        self.assertEqual(slot_key_labels_as_tuples(labels), [("SS", "Shortstop"), ("OF", "OF 1"), ("OF_2", "OF 2")])


class PlayerCardModelTests(unittest.TestCase):
    def test_player_card_model_with_photo(self) -> None:
        row = _roster_df().iloc[0]
        with patch(
            "player_photos.get_player_photo_info",
            return_value={
                "headshot_url": "https://img.mlbstatic.com/betts.png",
                "has_photo": True,
            },
        ):
            card = build_player_card_model(row, player_name="Mookie Betts")
        self.assertEqual(card.player_name, "Mookie Betts")
        self.assertTrue(card.has_photo)
        self.assertIn("betts.png", card.photo_html)

    def test_photo_fallback_without_player_id(self) -> None:
        html, has_photo = photo_html_for_player(player_name="Unknown Player", row=None)
        self.assertFalse(has_photo)
        self.assertIn("fl-photo-fallback", html)
        self.assertIn(initials_from_name("Unknown Player"), html)

    def test_empty_slot_model(self) -> None:
        slot = build_slot_key_labels(["C"])[0]
        empty = build_empty_slot_model(slot)
        self.assertEqual(empty.badge, "C")
        self.assertEqual(empty.position_name, "Catcher")


class BoardRenderTests(unittest.TestCase):
    def test_empty_slot_rendering(self) -> None:
        labels = build_slot_key_labels(["C"])
        cards = build_slot_cards(labels, {"C": ""}, _roster_df())
        html = render_slot_card_html(cards[0])
        self.assertIn("Open slot", html)
        self.assertIn("fl-slot-open", html)

    def test_bench_separation(self) -> None:
        labels = build_slot_key_labels(["C"])
        roster = _roster_df()[_roster_df()["Team"] == "Daniel"].copy()
        assignments = {"C": "Mookie Betts"}
        bench = bench_player_cards(roster, assignments, labels)
        self.assertEqual(len(bench), 1)
        self.assertEqual(bench[0].player_name, "Bench Hitter")
        html = render_bench_section_html(bench)
        self.assertIn("Bench Hitter", html)
        self.assertIn("fl-bench-grid", html)

    def test_filled_slot_board_contains_headshot(self) -> None:
        labels = build_slot_key_labels(["OF", "OF"])
        assignments = {"OF": "Mookie Betts", "OF_2": ""}
        cards = build_slot_cards(labels, assignments, _roster_df())
        board = render_starting_lineup_board_html(cards)
        self.assertIn("Mookie Betts", board)
        self.assertIn("OF 1", board)
        self.assertIn("Open slot", board)

    def test_mobile_width_css_present(self) -> None:
        st = MagicMock()
        st.html = MagicMock()
        inject_lineup_board_styles(st)
        if st.html.called:
            css = st.html.call_args[0][0]
        else:
            css = st.markdown.call_args[0][0]
        self.assertIn("@media (max-width: 768px)", css)
        self.assertIn("fl-slot-grid", css)

    def test_roster_board_html_includes_of_labels_and_photos(self) -> None:
        labels = build_slot_key_labels(["OF", "OF", "OF"])
        roster = _roster_df()[_roster_df()["Team"] == "Daniel"].copy()
        assignments = {"OF": "Mookie Betts", "OF_2": "", "OF_3": ""}
        html = render_roster_board_html(labels, assignments, roster)
        self.assertIn("OF 1", html)
        self.assertIn("OF 2", html)
        self.assertIn("OF 3", html)
        self.assertIn("Mookie Betts", html)
        self.assertIn("fl-player-photo", html)
        self.assertIn("fl-bench-grid", html)


class ValidationTests(unittest.TestCase):
    def test_duplicate_player_validation(self) -> None:
        roster = _roster_df()
        slots = ["C", "1B"]
        assignments = {"C": "Mookie Betts", "1B": "Mookie Betts"}
        result = validate_weekly_lineup(slots, assignments, roster)
        self.assertFalse(result["ok"])
        self.assertIn("Mookie Betts", result["duplicate_players"])

    def test_ineligible_player_validation(self) -> None:
        roster = _roster_df()
        slots = ["C"]
        assignments = {"C": "Mookie Betts"}
        result = validate_weekly_lineup(slots, assignments, roster)
        self.assertFalse(result["ok"])
        self.assertTrue(any("not eligible" in str(m).lower() for m in result["messages"]))


class TradedRosterRebuildTests(unittest.TestCase):
    def test_daniel_shows_betts_not_lindor_after_trade(self) -> None:
        daniel = _roster_df()[_roster_df()["Team"] == "Daniel"].copy()
        names = roster_names_for_team(daniel, "Daniel")
        self.assertIn("Mookie Betts", names)
        self.assertNotIn("Francisco Lindor", names)

    def test_team2_shows_lindor_not_betts_after_trade(self) -> None:
        team2 = _roster_df()[_roster_df()["Team"] == "Team 2"].copy()
        names = roster_names_for_team(team2, "Team 2")
        self.assertIn("Francisco Lindor", names)
        self.assertNotIn("Mookie Betts", names)


class EditorEquivalenceTests(unittest.TestCase):
    def test_dnd_and_dropdown_produce_same_assignments(self) -> None:
        roster = _roster_df()[ _roster_df()["Team"] == "Daniel"].copy()
        slot_keys = slot_key_labels_as_tuples(build_slot_key_labels(["C", "1B"]))
        dropdown_assignments = {"C": "Mookie Betts", "1B": "Bench Hitter"}
        containers = build_sortable_containers(slot_keys, dropdown_assignments, roster)
        dnd_assignments = assignments_from_sortable_containers(containers, slot_keys, roster)
        self.assertEqual(dnd_assignments, dropdown_assignments)


class SavedLineupPersistenceTests(unittest.TestCase):
    def test_saved_weekly_assignments_unchanged_by_ui_helpers(self) -> None:
        from fantasy_league_context import get_active_league_context, save_simulator_league_context

        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Mookie Betts", "Pick": 1, "Primary Position": "OF"},
                {"Team": "Daniel", "Player": "Bench Hitter", "Pick": 2, "Primary Position": "1B"},
            ]
        )
        save_simulator_league_context(session, board, my_team_name="Daniel")
        roster = _roster_df()[_roster_df()["Team"] == "Daniel"]
        slots = ["OF", "1B"]
        assignments = {"OF": "Mookie Betts", "1B": "Bench Hitter"}
        result = save_weekly_lineup(
            session,
            week=2,
            slots=slots,
            assignments=assignments,
            my_team="Daniel",
            roster_df=roster,
        )
        self.assertTrue(result.get("ok"))
        context = get_active_league_context(session)
        assert context is not None
        slot_map = assignments_to_slot_player_map(slots, assignments)
        saved = result["lineup"]["assignments"]
        self.assertEqual(saved.get("OF"), slot_map.get("OF"))


class TeamHeaderTests(unittest.TestCase):
    def test_team_header_model_counts(self) -> None:
        labels = build_slot_key_labels(["C", "1B", "2B"])
        roster = _roster_df()[_roster_df()["Team"] == "Daniel"]
        model = build_team_header_model(
            context={"my_team_name": "Daniel", "display_name": "Demo League"},
            team_name="Daniel",
            week=4,
            roster_df=roster,
            slot_labels=labels,
            assignments={"C": "Mookie Betts", "1B": "", "2B": ""},
        )
        self.assertEqual(model.team_name, "Daniel")
        self.assertEqual(model.league_name, "Demo League")
        self.assertEqual(model.filled_starters, 1)
        self.assertEqual(model.total_starter_slots, 3)
        self.assertTrue(model.is_active_team)


class WeeklyLineupPageSmokeTests(unittest.TestCase):
    def test_render_weekly_lineup_section_reaches_week_selectbox(self) -> None:
        from fantasy_weekly_lineup_ui import render_weekly_lineup_section
        from fantasy_league_context import save_simulator_league_context

        session: dict = {}
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Mookie Betts", "Pick": 1}])
        save_simulator_league_context(session, board, my_team_name="Daniel")
        roster = _roster_df()[_roster_df()["Team"] == "Daniel"]

        st = MagicMock()
        st.html = MagicMock()

        def _columns(n):
            count = n if isinstance(n, int) else len(n)
            return [MagicMock() for _ in range(max(int(count or 1), 1))]

        st.columns.side_effect = _columns
        st.selectbox.return_value = 1
        st.button.return_value = False

        with patch("fantasy_lineup_interactive_board.render_interactive_lineup_board", return_value=None):
            render_weekly_lineup_section(
                st,
                session,
                team_roster=roster,
                lineup_team="Daniel",
            )

        week_calls = [
            c for c in st.selectbox.call_args_list if c.kwargs.get("key") == "weekly_lineup_selected_week"
        ]
        self.assertEqual(len(week_calls), 1)
        self.assertFalse(st.radio.called)
        markdown_calls = [str(c.args[0]) for c in st.markdown.call_args_list if c.args]
        html_calls = [str(c.args[0]) for c in getattr(st, "html", MagicMock()).call_args_list if c.args]
        combined = " ".join(markdown_calls + html_calls)
        self.assertIn("fl-team-header", combined)


if __name__ == "__main__":
    unittest.main()
