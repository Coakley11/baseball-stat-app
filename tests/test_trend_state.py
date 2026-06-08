"""Tests for canonical Trend Value page state."""

from __future__ import annotations

import unittest

from trend_state import (
    TREND_DIRTY_KEY,
    apply_trend_source_state_from_ami,
    gather_chart_player,
    gather_trend_players_multi,
    is_trend_locally_dirty,
    mark_trend_local_edit,
    prepare_trend_top_filters,
    prepare_trend_value_page,
    restore_trend_page_filters,
    sync_trend_settings_change,
    write_canonical_trend_state,
)


def _resolve(name: str, label_map: dict) -> str | None:
    fn = " ".join(str(name).strip().split())
    if fn in label_map:
        return fn
    base = fn.split(" (")[0].strip()
    matches = [lbl for lbl in label_map if lbl.split(" (")[0] == base]
    if len(matches) == 1:
        return matches[0]
    return None


class TestTrendState(unittest.TestCase):
    def setUp(self) -> None:
        self.label_map = {
            "Francisco Lindor": "lindofr01",
            "Aaron Judge": "judgeaa01",
            "Lorenzo Cain": "cainlo01",
            "Juan Soto": "sotoju01",
        }

    def test_canonical_empty_multi_stays_empty(self) -> None:
        session = {
            "trend_state": {"chart_player": None, "players_multi": []},
            "trend_players_multi": [],
            "page_filter_state": {
                "Trend Value": {
                    "trend_players_multi": ["Lorenzo Cain"],
                    "single_trend_dashboard_player": "Lorenzo Cain",
                }
            },
        }
        gathered = gather_trend_players_multi(session, self.label_map, _resolve)
        self.assertEqual(gathered, [])

    def test_no_default_lorenzo_when_canonical_set(self) -> None:
        session = {
            "trend_state": {
                "chart_player": "Francisco Lindor",
                "players_multi": ["Francisco Lindor", "Aaron Judge"],
            }
        }
        players = prepare_trend_value_page(session, self.label_map, _resolve)
        self.assertEqual(players.get("chart_player"), "Francisco Lindor")
        self.assertEqual(session["single_trend_dashboard_player"], "Francisco Lindor")
        self.assertEqual(
            session["trend_players_multi"],
            ["Francisco Lindor", "Aaron Judge"],
        )

    def test_local_dirty_preserves_chart_player_edit(self) -> None:
        session = {
            "trend_state": {"chart_player": "Lorenzo Cain", "players_multi": []},
            "single_trend_dashboard_player": "Aaron Judge",
        }
        mark_trend_local_edit(session)
        lbl = gather_chart_player(session, self.label_map, _resolve)
        self.assertEqual(lbl, "Aaron Judge")

    def test_restore_blocked_when_locally_dirty(self) -> None:
        session = {"trend_plot_stat": "HR", "trend_chart_mode": "Smoothed Moving Average"}
        mark_trend_local_edit(session)
        store = {"Trend Value": {"trend_plot_stat": "OPS", "trend_chart_mode": "Actual Values"}}
        self.assertFalse(restore_trend_page_filters(session, store))
        self.assertEqual(session["trend_plot_stat"], "HR")

    def test_ami_return_restores_players(self) -> None:
        session: dict = {}
        source = {
            "source_page": "Trend Value",
            "entity_params": {
                "player_label": "Francisco Lindor",
                "trend_players_multi": ["Francisco Lindor", "Aaron Judge"],
            },
            "chart_params": {
                "trend_players_multi": ["Francisco Lindor", "Aaron Judge"],
                "stats": ["HR", "OPS"],
            },
            "filter_params": {"trend_plot_stat": "HR", "trend_chart_mode": "Actual Values"},
        }
        apply_trend_source_state_from_ami(session, source)
        self.assertEqual(session["single_trend_dashboard_player"], "Francisco Lindor")
        self.assertEqual(
            session["trend_players_multi"],
            ["Francisco Lindor", "Aaron Judge"],
        )
        self.assertFalse(session.get(TREND_DIRTY_KEY))

    def test_write_canonical_syncs_page_filter(self) -> None:
        session: dict = {}
        write_canonical_trend_state(
            session,
            chart_player="Aaron Judge",
            players_multi=["Aaron Judge", "Juan Soto"],
            reason="test",
        )
        block = session["page_filter_state"]["Trend Value"]
        self.assertEqual(block["single_trend_dashboard_player"], "Aaron Judge")
        self.assertEqual(block["trend_players_multi"], ["Aaron Judge", "Juan Soto"])
        self.assertFalse(is_trend_locally_dirty(session))

    def test_top_filter_settings_sync_to_canonical_meta(self) -> None:
        session = {
            "trend_state": {
                "filters": {"trend_lag": 3, "trend_min_g": 50, "trend_position_filter": "All positions"},
            },
            "page_filter_state": {"Trend Value": {"trend_lag": 3, "trend_min_g": 50}},
        }
        session["trend_lag"] = 5
        session["trend_min_g"] = 120
        session["trend_position_filter"] = "OF"
        sync_trend_settings_change(session, reason="settings_change")
        meta = session["trend_state"]
        self.assertTrue(is_trend_locally_dirty(session))
        self.assertEqual(meta["filters"]["trend_lag"], 5)
        self.assertEqual(meta["filters"]["trend_min_g"], 120)
        self.assertEqual(meta["filters"]["trend_position_filter"], "OF")
        block = session["page_filter_state"]["Trend Value"]
        self.assertEqual(block["trend_lag"], 5)
        self.assertEqual(block["trend_min_g"], 120)
        self.assertEqual(block["trend_position_filter"], "OF")

    def test_prepare_top_filters_seeds_from_canonical_before_widgets(self) -> None:
        session = {
            "trend_state": {
                "filters": {"trend_lag": 4, "trend_min_g": 75, "trend_position_filter": "SS"},
            },
            "page_filter_state": {"Trend Value": {"trend_lag": 3, "trend_min_g": 50}},
        }
        prepare_trend_top_filters(session)
        self.assertEqual(session["trend_lag"], 4)
        self.assertEqual(session["trend_min_g"], 75)
        self.assertEqual(session["trend_position_filter"], "SS")


if __name__ == "__main__":
    unittest.main()
