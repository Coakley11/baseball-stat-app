"""Regression tests for Fantasy Lineup canonical state flow and stat lines.

Covers the two live fixes:
1. Drag-and-drop (mouse + touch) persists to a single canonical per-week state,
   survives rerun, appears on the board, saves, and is not reset by the inactive
   Classic Dropdown editor.
2. Hitter cards show R · HR · RBI · SB · AVG · OPS with graceful degradation.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from fantasy_lineup_ui import (
    build_slot_key_labels,
    compact_stat_line_from_row,
    format_rate_stat,
    render_roster_board_html,
    slot_key_labels_as_tuples,
)
from fantasy_league_context import get_active_league_context, save_simulator_league_context
from fantasy_weekly_lineup import get_saved_weekly_lineup, save_weekly_lineup
from fantasy_weekly_lineup_dnd import (
    assignments_from_sortable_containers,
    bench_container_header,
    build_sortable_containers,
    slot_container_header,
)
from fantasy_weekly_lineup_ui import (
    assignment_signature,
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

    def test_avg_and_ops_not_truncated_away(self) -> None:
        line = compact_stat_line_from_row(
            {"R": 1, "HR": 2, "RBI": 3, "SB": 4, "BA": 0.288, "OPS": 0.911}
        )
        self.assertIn("AVG .288", line)
        self.assertIn("OPS .911", line)

    def test_rate_stat_leading_zero_stripped_but_keeps_over_one(self) -> None:
        self.assertEqual(format_rate_stat(0.320), ".320")
        self.assertEqual(format_rate_stat(1.045), "1.045")

    def test_nan_values_skipped(self) -> None:
        line = compact_stat_line_from_row(
            {"R": float("nan"), "HR": 9, "RBI": float("nan"), "SB": 3, "OPS": 0.812}
        )
        self.assertEqual(line, "HR 9 · SB 3 · OPS .812")

    def test_board_card_shows_runs_and_avg(self) -> None:
        roster = _daniel_roster()
        labels = build_slot_key_labels(["OF"])
        board = render_roster_board_html(labels, {"OF": "Mookie Betts"}, roster)
        self.assertIn("R 52", board)
        self.assertIn("AVG .320", board)
        self.assertIn("OPS .993", board)


class CanonicalStateFlowTests(unittest.TestCase):
    """Drag from bench → slot → rerun → save → refresh, plus back-to-bench."""

    def _setup_context(self, session: dict) -> pd.DataFrame:
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Mookie Betts", "Pick": 1, "Primary Position": "OF"},
                {"Team": "Daniel", "Player": "Bench Hitter", "Pick": 2, "Primary Position": "OF"},
            ]
        )
        save_simulator_league_context(session, board, my_team_name="Daniel")
        return board

    def test_touch_or_mouse_drag_persists_survives_rerun_and_saves(self) -> None:
        session: dict = {}
        self._setup_context(session)
        roster = _daniel_roster()
        slots = ["OF"]
        labels = build_slot_key_labels(slots)
        slot_keys = slot_key_labels_as_tuples(labels)
        week = 3
        canon_key = canonical_week_key(PREFIX, week)

        # 1. player begins on Bench (canonical empty)
        assignments = ensure_canonical_assignments(
            session, canon_key=canon_key, slot_keys=slot_keys, saved_assignments={}
        )
        self.assertEqual(assignments, {"OF": ""})

        # 2. drag Betts (touch or mouse both yield the same sorted containers)
        dragged = [
            {"header": slot_container_header("OF", "OF 1"), "items": ["Mookie Betts"]},
            {"header": bench_container_header(), "items": ["Bench Hitter"]},
        ]
        new_assignments = assignments_from_sortable_containers(dragged, slot_keys, roster)

        # 3. rerun: reconcile updates canonical and signals a (guarded) rerun
        changed = reconcile_editor_assignments(
            session, canon_key=canon_key, slot_keys=slot_keys, new_assignments=new_assignments
        )
        self.assertTrue(changed)

        # 4. player remains in the slot after rerun
        after = ensure_canonical_assignments(
            session, canon_key=canon_key, slot_keys=slot_keys, saved_assignments={}
        )
        self.assertEqual(after["OF"], "Mookie Betts")

        # no rerun loop: rebuilding from canonical yields identical output
        containers = build_sortable_containers(slot_keys, after, roster)
        replay = assignments_from_sortable_containers(containers, slot_keys, roster)
        self.assertEqual(
            assignment_signature(replay, slot_keys), assignment_signature(after, slot_keys)
        )
        self.assertFalse(
            reconcile_editor_assignments(
                session, canon_key=canon_key, slot_keys=slot_keys, new_assignments=replay
            )
        )

        # 5. roster board shows the player
        board = render_roster_board_html(labels, after, roster)
        self.assertIn("Mookie Betts", board)

        # 6. save persists the canonical assignments
        save_result = save_weekly_lineup(
            session,
            week=week,
            slots=slots,
            assignments=after,
            my_team="Daniel",
            roster_df=roster,
        )
        self.assertTrue(save_result.get("ok"))

        # 7. refresh (fresh session) restores from saved lineup
        context = get_active_league_context(session)
        assert context is not None
        saved = get_saved_weekly_lineup(context, week)
        assert saved is not None
        fresh_session: dict = {}
        restored = ensure_canonical_assignments(
            fresh_session,
            canon_key=canon_key,
            slot_keys=slot_keys,
            saved_assignments=dict(saved.get("assignments") or {}),
        )
        self.assertEqual(restored.get("OF"), "Mookie Betts")

    def test_drag_starter_back_to_bench_clears_slot(self) -> None:
        session: dict = {}
        roster = _daniel_roster()
        slots = ["OF", "OF"]
        labels = build_slot_key_labels(slots)
        slot_keys = slot_key_labels_as_tuples(labels)
        week = 5
        canon_key = canonical_week_key(PREFIX, week)
        # start with Betts in OF 1
        session[canon_key] = {"OF": "Mookie Betts", "OF_2": ""}

        moved_back = [
            {"header": slot_container_header("OF", "OF 1"), "items": []},
            {"header": slot_container_header("OF_2", "OF 2"), "items": []},
            {"header": bench_container_header(), "items": ["Mookie Betts", "Bench Hitter"]},
        ]
        new_assignments = assignments_from_sortable_containers(moved_back, slot_keys, roster)
        changed = reconcile_editor_assignments(
            session, canon_key=canon_key, slot_keys=slot_keys, new_assignments=new_assignments
        )
        self.assertTrue(changed)
        self.assertEqual(session[canon_key]["OF"], "")

    def test_weeks_are_isolated(self) -> None:
        session: dict = {}
        roster = _daniel_roster()
        slot_keys = slot_key_labels_as_tuples(build_slot_key_labels(["OF"]))
        week1 = canonical_week_key(PREFIX, 1)
        week2 = canonical_week_key(PREFIX, 2)
        session[week1] = {"OF": "Mookie Betts"}
        assignments_w2 = ensure_canonical_assignments(
            session, canon_key=week2, slot_keys=slot_keys, saved_assignments={}
        )
        self.assertEqual(assignments_w2["OF"], "")
        self.assertEqual(session[week1]["OF"], "Mookie Betts")

    def test_inactive_dropdown_widgets_do_not_reset_canonical(self) -> None:
        """A stale dropdown widget value must not overwrite canonical state."""
        session: dict = {}
        roster = _daniel_roster()
        slot_keys = slot_key_labels_as_tuples(build_slot_key_labels(["OF"]))
        week = 7
        canon_key = canonical_week_key(PREFIX, week)
        session[canon_key] = {"OF": "Mookie Betts"}
        # A leftover dropdown widget key (separate namespace) should be ignored.
        session[f"{PREFIX}_dd_{week}_OF"] = ""
        assignments = ensure_canonical_assignments(
            session, canon_key=canon_key, slot_keys=slot_keys, saved_assignments={}
        )
        self.assertEqual(assignments["OF"], "Mookie Betts")


class DragDropRenderTests(unittest.TestCase):
    """Render-level: Drag & Drop mode never instantiates dropdown widgets."""

    def _mock_st(self):
        st = MagicMock()
        st.html = MagicMock()

        def _columns(n):
            count = n if isinstance(n, int) else len(n)
            return [MagicMock() for _ in range(max(int(count or 1), 1))]

        st.columns.side_effect = _columns
        st.selectbox.return_value = 1
        st.radio.return_value = "Drag & Drop"
        st.button.return_value = False
        st.expander.return_value.__enter__ = MagicMock(return_value=MagicMock())
        st.expander.return_value.__exit__ = MagicMock(return_value=False)
        return st

    def test_dnd_mode_does_not_instantiate_dropdown_selectboxes(self) -> None:
        session: dict = {"weekly_lineup_editor_mode": "Drag & Drop"}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Mookie Betts", "Pick": 1, "Primary Position": "OF"},
                {"Team": "Daniel", "Player": "Bench Hitter", "Pick": 2, "Primary Position": "OF"},
            ]
        )
        save_simulator_league_context(session, board, my_team_name="Daniel")
        roster = _daniel_roster()
        st = self._mock_st()

        with patch("streamlit_sortables.sort_items", side_effect=lambda containers, **kw: containers):
            render_weekly_lineup_section(st, session, team_roster=roster, lineup_team="Daniel")

        dropdown_calls = [
            c
            for c in st.selectbox.call_args_list
            if str(c.kwargs.get("key", "")).startswith("weekly_lineup_dd_")
        ]
        self.assertEqual(dropdown_calls, [])

    def test_dnd_drag_updates_canonical_and_triggers_guarded_rerun(self) -> None:
        session: dict = {"weekly_lineup_editor_mode": "Drag & Drop"}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Mookie Betts", "Pick": 1, "Primary Position": "OF"},
                {"Team": "Daniel", "Player": "Bench Hitter", "Pick": 2, "Primary Position": "OF"},
            ]
        )
        save_simulator_league_context(session, board, my_team_name="Daniel")
        roster = _daniel_roster()
        st = self._mock_st()

        def _fake_sort(containers, **kw):
            out = []
            for c in containers:
                cc = {"header": c["header"], "items": list(c["items"])}
                if "__bench__" in cc["header"]:
                    cc["items"] = [n for n in cc["items"] if n != "Mookie Betts"]
                out.append(cc)
            for cc in out:
                if "__slot__" in cc["header"] and not cc["items"]:
                    cc["items"] = ["Mookie Betts"]
                    break
            return out

        with patch("streamlit_sortables.sort_items", side_effect=_fake_sort):
            render_weekly_lineup_section(st, session, team_roster=roster, lineup_team="Daniel")

        self.assertTrue(st.rerun.called)
        canon = session.get(canonical_week_key(PREFIX, 1)) or {}
        self.assertIn("Mookie Betts", canon.values())


if __name__ == "__main__":
    unittest.main()
