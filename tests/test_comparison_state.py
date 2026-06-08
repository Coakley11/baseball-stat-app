"""Tests for canonical Comparison Tool player state."""

from __future__ import annotations

import unittest

from comparison_state import (
    gather_comparison_players,
    normalize_compare_label,
    prepare_comparison_tool_page,
    reconcile_compare_player_list,
    write_canonical_comparison_state,
)


def _resolve(name: str, label_map: dict) -> str | None:
    fn = " ".join(str(name).strip().split())
    if fn in label_map:
        return fn
    base = fn.split(" (")[0].strip()
    matches = [lbl for lbl in label_map if lbl.split(" (")[0] == base]
    if len(matches) == 1:
        return matches[0]
    if base in label_map:
        return base
    return None


class TestComparisonState(unittest.TestCase):
    def setUp(self) -> None:
        self.label_map = {
            "Juan Soto": "sotoju01",
            "Miguel Cabrera": "cabremi01",
            "Francisco Lindor": "lindofr01",
            "Melky Cabrera": "cabreme01",
        }

    def test_legacy_team_suffix_maps_to_canonical(self) -> None:
        lbl = normalize_compare_label("Miguel Cabrera (DET)", self.label_map, _resolve)
        self.assertEqual(lbl, "Miguel Cabrera")

    def test_reconcile_drops_invalid_keeps_valid(self) -> None:
        out = reconcile_compare_player_list(
            ["Juan Soto (NYY)", "Miguel Cabrera (DET)", "Not A Player"],
            self.label_map,
            _resolve,
        )
        self.assertEqual(out, ["Juan Soto", "Miguel Cabrera"])

    def test_gather_merges_sig_when_compare_empty(self) -> None:
        session = {
            "compare_players": [],
            "sig_player_a_clean": "Juan Soto (NYY)",
            "sig_player_b_clean": "Miguel Cabrera (DET)",
        }
        gathered = gather_comparison_players(session, self.label_map, _resolve)
        self.assertEqual(gathered, ["Juan Soto", "Miguel Cabrera"])

    def test_write_canonical_syncs_all_keys(self) -> None:
        session: dict = {}
        write_canonical_comparison_state(session, ["Juan Soto", "Miguel Cabrera"], reason="test")
        self.assertEqual(session["compare_players"], ["Juan Soto", "Miguel Cabrera"])
        self.assertEqual(session["sig_player_a_clean"], "Juan Soto")
        self.assertEqual(session["sig_player_b_clean"], "Miguel Cabrera")
        meta = session["comparison_state"]
        self.assertEqual(meta["players"], ["Juan Soto", "Miguel Cabrera"])

    def test_prepare_reconciles_page_filter_legacy_labels(self) -> None:
        session = {
            "page_filter_state": {
                "Comparison Tool": {
                    "compare_players": ["Juan Soto (NYY)", "Miguel Cabrera (DET)"],
                }
            }
        }
        players = prepare_comparison_tool_page(session, self.label_map, _resolve)
        self.assertEqual(players, ["Juan Soto", "Miguel Cabrera"])
        self.assertEqual(session["compare_players"], ["Juan Soto", "Miguel Cabrera"])


if __name__ == "__main__":
    unittest.main()
