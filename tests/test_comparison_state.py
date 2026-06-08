"""Tests for canonical Comparison Tool player state."""

from __future__ import annotations

import unittest

from comparison_state import (
    COMPARISON_DIRTY_KEY,
    clear_comparison_local_edit,
    gather_comparison_players,
    is_comparison_locally_dirty,
    normalize_compare_label,
    prepare_comparison_tool_page,
    reconcile_compare_player_list,
    sync_compare_from_multiselect,
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
            "Melky Cabrera": "cabreme01",
            "Francisco Lindor": "lindofr01",
            "Aaron Judge": "judgeaa01",
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

    def test_gather_empty_widget_uses_saved_not_sig(self) -> None:
        session = {
            "compare_players": [],
            "compare_players_saved": ["Juan Soto"],
            "sig_player_a_clean": "Juan Soto (NYY)",
            "sig_player_b_clean": "Miguel Cabrera (DET)",
        }
        gathered = gather_comparison_players(session, self.label_map, _resolve)
        self.assertEqual(gathered, ["Juan Soto"])

    def test_gather_uses_saved_when_widget_not_set(self) -> None:
        session = {
            "compare_players_saved": ["Juan Soto", "Melky Cabrera"],
        }
        gathered = gather_comparison_players(session, self.label_map, _resolve)
        self.assertEqual(gathered, ["Juan Soto", "Melky Cabrera"])

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

    def test_phone_like_edit_flow(self) -> None:
        session: dict = {
            "compare_players": ["Juan Soto", "Melky Cabrera"],
            "compare_players_saved": ["Juan Soto", "Melky Cabrera"],
            "sig_player_a_clean": "Juan Soto",
            "sig_player_b_clean": "Melky Cabrera",
            "page_filter_state": {
                "Comparison Tool": {
                    "compare_players": ["Juan Soto", "Melky Cabrera"],
                    "sig_player_a_clean": "Juan Soto",
                    "sig_player_b_clean": "Melky Cabrera",
                }
            },
        }
        write_canonical_comparison_state(
            session, ["Juan Soto", "Melky Cabrera"], reason="cloud_restore"
        )
        self.assertFalse(is_comparison_locally_dirty(session))

        session["compare_players"] = ["Melky Cabrera"]
        sync_compare_from_multiselect(session, ["Melky Cabrera"], self.label_map, _resolve)
        self.assertTrue(is_comparison_locally_dirty(session))
        self.assertEqual(session["comparison_state"]["players"], ["Melky Cabrera"])
        self.assertEqual(session["sig_player_a_clean"], "Melky Cabrera")
        self.assertNotIn("sig_player_b_clean", session)

        prepare_comparison_tool_page(session, self.label_map, _resolve)
        self.assertEqual(session["compare_players"], ["Melky Cabrera"])

        session["compare_players"] = []
        sync_compare_from_multiselect(session, [], self.label_map, _resolve)
        self.assertEqual(session["comparison_state"]["players"], [])
        prepare_comparison_tool_page(session, self.label_map, _resolve)
        self.assertEqual(session["compare_players"], [])

        session["compare_players"] = ["Francisco Lindor", "Aaron Judge"]
        sync_compare_from_multiselect(
            session, ["Francisco Lindor", "Aaron Judge"], self.label_map, _resolve
        )
        prepare_comparison_tool_page(session, self.label_map, _resolve)
        self.assertEqual(
            session["comparison_state"]["players"],
            ["Francisco Lindor", "Aaron Judge"],
        )
        self.assertNotIn("Juan Soto", session["compare_players"])
        self.assertNotIn("Melky Cabrera", session["compare_players"])

        gathered = gather_comparison_players(session, self.label_map, _resolve)
        self.assertEqual(gathered, ["Francisco Lindor", "Aaron Judge"])

        clear_comparison_local_edit(session)
        self.assertFalse(session.get(COMPARISON_DIRTY_KEY))


if __name__ == "__main__":
    unittest.main()
