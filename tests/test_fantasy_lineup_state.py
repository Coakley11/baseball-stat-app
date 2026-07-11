"""Regression tests for Fantasy Lineup canonical state flow and stat lines."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from fantasy_lineup_interactive_board import (
    BENCH_ZONE,
    apply_board_drop,
    build_interactive_board_payload,
    parse_board_drop_result,
)
from fantasy_lineup_ui import (
    build_slot_key_labels,
    compact_stat_line_from_row,
    format_rate_stat,
    render_roster_board_html,
    slot_key_labels_as_tuples,
)
from fantasy_league_context import get_active_league_context, save_simulator_league_context
from fantasy_weekly_lineup import get_saved_weekly_lineup, save_weekly_lineup
from fantasy_weekly_lineup_ui import (
    assignment_signature,
    build_open_slot_prompts,
    canonical_week_key,
    ensure_canonical_assignments,
    reconcile_editor_assignments,
    render_weekly_lineup_section,
)

PREFIX = "weekly_lineup"


def _daniel_roster() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Team": "Daniel",
                "Player": "Mookie Betts",
                "Primary Position": "OF",
                "R": 52,
                "HR": 21,
                "RBI": 50,
                "SB": 7,
                "BA": 0.320,
                "OPS": 0.993,
                "player_id": "betts1",
            },
            {
                "Team": "Daniel",
                "Player": "Bench Hitter",
                "Primary Position": "OF",
                "R": 30,
                "HR": 5,
                "RBI": 20,
                "SB": 1,
                "AVG": 0.250,
                "OPS": 0.700,
                "player_id": "bench1",
            },
        ]
    )


class StatLineTests(unittest.TestCase):
    def test_all_six_categories_present_and_ordered(self) -> None:
        line = compact_stat_line_from_row(
            {"R": 52, "HR": 21, "RBI": 50, "SB": 7, "BA": 0.320, "OPS": 0.993}
        )
        self.assertEqual(line, "R 52 · HR 21 · RBI 50 · SB 7 · AVG .320 · OPS .993")

    def test_avg_alias_supported(self) -> None:
        line = compact_stat_line_from_row({"R": 10, "AVG": 0.301, "OPS": 0.850})
        self.assertIn("AVG .301", line)
        self.assertIn("R 10", line)

    def test_missing_columns_degrade_cleanly(self) -> None:
        line = compact_stat_line_from_row({"HR": 12, "RBI": 40})
        self.assertEqual(line, "HR 12 · RBI 40")

    def test_rate_stat_leading_zero_stripped(self) -> None:
        self.assertEqual(format_rate_stat(0.320), ".320")


class InteractiveBoardTests(unittest.TestCase):
    def test_bench_to_slot_drop(self) -> None:
        roster = _daniel_roster()
        slot_keys = slot_key_labels_as_tuples(build_slot_key_labels(["OF"]))
        assignments = {"OF": ""}
        updated = apply_board_drop(
            assignments,
            slot_keys,
            player="Mookie Betts",
            target="OF",
            roster_df=roster,
        )
        self.assertEqual(updated["OF"], "Mookie Betts")

    def test_starter_back_to_bench_clears_slot(self) -> None:
        roster = _daniel_roster()
        slot_keys = slot_key_labels_as_tuples(build_slot_key_labels(["OF"]))
        assignments = {"OF": "Mookie Betts"}
        updated = apply_board_drop(
            assignments,
            slot_keys,
            player="Mookie Betts",
            target=BENCH_ZONE,
            roster_df=roster,
        )
        self.assertEqual(updated["OF"], "")

    def test_payload_includes_faces_and_slots(self) -> None:
        labels = build_slot_key_labels(["OF"])
        payload = build_interactive_board_payload(labels, {"OF": ""}, _daniel_roster())
        self.assertEqual(len(payload["slots"]), 1)
        self.assertEqual(len(payload["bench"]), 2)
        self.assertEqual(len(payload["roster"]), 2)
        self.assertIn("Mookie Betts", payload["faces"])
        self.assertIn("Mookie Betts", payload["roster"])

    def test_payload_bench_excludes_assigned_starter(self) -> None:
        labels = build_slot_key_labels(["OF"])
        payload = build_interactive_board_payload(labels, {"OF": "Mookie Betts"}, _daniel_roster())
        self.assertEqual([p["name"] for p in payload["bench"]], ["Bench Hitter"])

    def test_parse_board_drop_result(self) -> None:
        raw = json.dumps({"player": "Mookie Betts", "target": "OF", "assignments": {"OF": "Mookie Betts"}})
        parsed = parse_board_drop_result(raw)
        assert parsed is not None
        self.assertEqual(parsed["player"], "Mookie Betts")


class CanonicalStateFlowTests(unittest.TestCase):
    def test_drag_persists_save_and_refresh(self) -> None:
        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Mookie Betts", "Pick": 1, "Primary Position": "OF"},
                {"Team": "Daniel", "Player": "Bench Hitter", "Pick": 2, "Primary Position": "OF"},
            ]
        )
        save_simulator_league_context(session, board, my_team_name="Daniel")
        roster = _daniel_roster()
        slots = ["OF"]
        slot_keys = slot_key_labels_as_tuples(build_slot_key_labels(slots))
        week = 3
        canon_key = canonical_week_key(PREFIX, week)

        assignments = ensure_canonical_assignments(
            session, canon_key=canon_key, slot_keys=slot_keys, saved_assignments={}
        )
        new_assignments = apply_board_drop(
            assignments, slot_keys, player="Mookie Betts", target="OF", roster_df=roster
        )
        self.assertTrue(
            reconcile_editor_assignments(
                session, canon_key=canon_key, slot_keys=slot_keys, new_assignments=new_assignments
            )
        )
        after = ensure_canonical_assignments(
            session, canon_key=canon_key, slot_keys=slot_keys, saved_assignments={}
        )
        self.assertEqual(after["OF"], "Mookie Betts")

        save_result = save_weekly_lineup(
            session,
            week=week,
            slots=slots,
            assignments=after,
            my_team="Daniel",
            roster_df=roster,
        )
        self.assertTrue(save_result.get("ok"))

        context = get_active_league_context(session)
        assert context is not None
        saved = get_saved_weekly_lineup(context, week, team="Daniel", session=session)
        assert saved is not None
        fresh: dict = {}
        restored = ensure_canonical_assignments(
            fresh,
            canon_key=canon_key,
            slot_keys=slot_keys,
            saved_assignments=dict(saved.get("assignments") or {}),
        )
        self.assertEqual(restored.get("OF"), "Mookie Betts")


class OpenSlotPromptTests(unittest.TestCase):
    def test_only_open_positions_listed(self) -> None:
        labels = build_slot_key_labels(["C", "1B", "3B", "UTIL"])
        rows = build_open_slot_prompts(labels, {"C": "Mookie Betts", "1B": "Bench Hitter", "3B": "", "UTIL": ""})
        texts = [r["text"] for r in rows]
        self.assertEqual(texts, ["Third Base is empty", "UTIL is empty"])
        self.assertNotIn("Catcher is empty", texts)
        self.assertNotIn("First Base is empty", texts)

    def test_single_of_open_uses_slot_label(self) -> None:
        labels = build_slot_key_labels(["OF", "OF", "OF"])
        rows = build_open_slot_prompts(
            labels, {"OF": "", "OF_2": "Mookie Betts", "OF_3": "Bench Hitter"}
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "OF 1 is empty")
        self.assertEqual(rows[0]["waiver_label"], "Outfield")

    def test_multiple_of_open_combined(self) -> None:
        labels = build_slot_key_labels(["OF", "OF", "OF"])
        rows = build_open_slot_prompts(labels, {"OF": "", "OF_2": "", "OF_3": "Mookie Betts"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "2 Outfield spots are empty")
        self.assertEqual(rows[0]["waiver_label"], "Outfield")

    def test_waiver_labels_for_standard_positions(self) -> None:
        labels = build_slot_key_labels(["C", "SS"])
        rows = build_open_slot_prompts(labels, {"C": "", "SS": ""})
        self.assertEqual(rows[0]["waiver_label"], "Catcher")
        self.assertEqual(rows[1]["waiver_label"], "Shortstop")


class CircleBoardRenderTests(unittest.TestCase):
    def test_no_editor_mode_or_dropdown_widgets(self) -> None:
        from fantasy_league_context import get_active_league_context, upsert_league_context
        from fantasy_league_lineup_format import CONFIG_SOURCE_SIMULATOR, apply_lineup_format_to_context

        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Mookie Betts", "Pick": 1, "Primary Position": "OF"},
                {"Team": "Daniel", "Player": "Bench Hitter", "Pick": 2, "Primary Position": "OF"},
            ]
        )
        save_simulator_league_context(session, board, my_team_name="Daniel")
        context = get_active_league_context(session)
        assert context is not None
        context = apply_lineup_format_to_context(
            context,
            lineup_slots=["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL"],
            roster_capacity=9,
            configured_by="daniel",
            configuration_source=CONFIG_SOURCE_SIMULATOR,
        )
        upsert_league_context(session, context)
        roster = _daniel_roster()
        st = MagicMock()
        st.html = MagicMock()
        st.columns.side_effect = lambda n, **kw: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
        st.selectbox.return_value = 1
        st.button.return_value = False

        with patch("fantasy_lineup_interactive_board.render_interactive_lineup_board", return_value=None):
            render_weekly_lineup_section(st, session, team_roster=roster, lineup_team="Daniel")

        self.assertFalse(st.radio.called)
        dd_calls = [c for c in st.selectbox.call_args_list if "weekly_lineup_dd_" in str(c.kwargs.get("key", ""))]
        self.assertEqual(dd_calls, [])
        save_calls = [c for c in st.button.call_args_list if c.kwargs.get("key") == "weekly_lineup_save_btn"]
        self.assertEqual(len(save_calls), 1)
        self.assertEqual(save_calls[0].args[0], "Save Lineup")


if __name__ == "__main__":
    unittest.main()
