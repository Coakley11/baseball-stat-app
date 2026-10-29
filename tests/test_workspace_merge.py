"""Three-way workspace merge (workspace_merge): who wins each field, and when it is a conflict."""

from __future__ import annotations

import unittest

import workspace_merge as wm

HIST = "Historical Explorer"
TREND = "Trend Value"


def pf(**blocks):
    return {"page_filter_state": blocks}


class MergeRulesTests(unittest.TestCase):
    def merge(self, base, local, remote):
        return wm.three_way_merge(wm.compact_base(base), local, remote)

    def test_each_side_keeps_the_fields_only_it_changed(self) -> None:
        base = pf(**{HIST: {"hist_HR_min": 0}, TREND: {"trend_lag": 3}})
        local = pf(**{HIST: {"hist_HR_min": 40}, TREND: {"trend_lag": 3}})   # this device: HR > 40
        remote = pf(**{HIST: {"hist_HR_min": 0}, TREND: {"trend_lag": 5}})   # phone: 5-year window
        merged, conflicts = self.merge(base, local, remote)
        self.assertEqual(conflicts, [])
        self.assertEqual(merged["page_filter_state"][HIST]["hist_HR_min"], 40)
        self.assertEqual(merged["page_filter_state"][TREND]["trend_lag"], 5)

    def test_two_filters_on_one_page_never_collide(self) -> None:
        base = pf(**{HIST: {"hist_HR_min": 0, "hist_2B_min": 0}})
        merged, conflicts = self.merge(
            base,
            pf(**{HIST: {"hist_HR_min": 40, "hist_2B_min": 0}}),
            pf(**{HIST: {"hist_HR_min": 0, "hist_2B_min": 30}}),
        )
        self.assertEqual(conflicts, [])
        self.assertEqual(merged["page_filter_state"][HIST], {"hist_HR_min": 40, "hist_2B_min": 30})

    def test_same_field_changed_differently_is_a_conflict_and_the_account_side_is_written(self) -> None:
        base = pf(**{HIST: {"hist_HR_min": 0}})
        merged, conflicts = self.merge(base, pf(**{HIST: {"hist_HR_min": 40}}), pf(**{HIST: {"hist_HR_min": 30}}))
        self.assertEqual(conflicts, [("page_filter_state", HIST, "hist_HR_min")])
        self.assertEqual(merged["page_filter_state"][HIST]["hist_HR_min"], 30)

    def test_setting_back_to_default_is_a_real_edit(self) -> None:
        base = pf(**{HIST: {"hist_HR_min": 40}})
        merged, conflicts = self.merge(base, pf(**{HIST: {"hist_HR_min": 0}}), pf(**{HIST: {"hist_HR_min": 40}}))
        self.assertEqual((conflicts, merged["page_filter_state"][HIST]["hist_HR_min"]), ([], 0))

    def test_queue_keeps_both_devices_additions_and_either_sides_removal(self) -> None:
        base = {"draft_queue": ["A", "B", "C"]}
        merged, conflicts = self.merge(base, {"draft_queue": ["B", "C", "E"]}, {"draft_queue": ["A", "B", "C", "D"]})
        self.assertEqual(conflicts, [])
        self.assertEqual(merged["draft_queue"], ["B", "C", "D", "E"])  # A removed here, D added there

    def test_stale_device_that_did_not_touch_the_queue_cannot_shrink_it(self) -> None:
        base = {"draft_queue": ["A", "B", "C"], "historical_state": {"filters": {"hist_HR_min": 0}}}
        local = {"draft_queue": ["A", "B", "C"], "historical_state": {"filters": {"hist_HR_min": 40}}}
        remote = {"draft_queue": ["A", "B", "C", "D"], "historical_state": {"filters": {"hist_HR_min": 0}}}
        merged, conflicts = self.merge(base, local, remote)
        self.assertEqual(conflicts, [])
        self.assertEqual(merged["draft_queue"], ["A", "B", "C", "D"])
        self.assertEqual(merged["historical_state"]["filters"]["hist_HR_min"], 40)

    def test_simulator_board_is_atomic_never_merged_pick_by_pick(self) -> None:
        board = lambda *p: {"table_records": [{"Player": x} for x in p]}  # noqa: E731
        base = {"draft_room_table": board("Ohtani")}
        merged, conflicts = self.merge(base, {"draft_room_table": board("Ohtani", "Judge")},
                                       {"draft_room_table": board("Ohtani", "Soto")})
        self.assertEqual(conflicts, [("draft_room_table",)])
        self.assertEqual(merged["draft_room_table"], board("Ohtani", "Soto"))
        self.assertTrue(wm.board_conflicted(conflicts))                     # handed to draft_board_reconcile
        self.assertFalse(wm.board_conflicted([("page_filter_state", "Historical Explorer", "hr_min")]))
        # An undo made only here is kept, even though the account's board is larger.
        merged, conflicts = self.merge({"draft_room_table": board("Ohtani", "Judge")},
                                       {"draft_room_table": board("Ohtani")},
                                       {"draft_room_table": board("Ohtani", "Judge")})
        self.assertEqual((conflicts, merged["draft_room_table"]), ([], board("Ohtani")))

    def test_opening_the_board_on_two_devices_is_not_a_change(self) -> None:
        board = lambda when, *p: {"_persisted_at": when, "canonical_draft_meta": {"last_updated_at": when},  # noqa: E731
                                  "table_records": [{"Player": x} for x in p]}
        base = {"draft_room_table": board("t0", "Ohtani"), "page_filter_state": {"Historical Explorer": {"hist_HR_min": 0}}}
        local = {"draft_room_table": board("t1", "Ohtani"), "page_filter_state": {"Historical Explorer": {"hist_HR_min": 40}}}
        remote = {"draft_room_table": board("t2", "Ohtani"), "page_filter_state": {"Historical Explorer": {"hist_HR_min": 0}}}
        merged, conflicts = self.merge(wm.compact_base(base), local, remote)
        self.assertEqual(conflicts, [])
        self.assertEqual(merged["page_filter_state"]["Historical Explorer"]["hist_HR_min"], 40)
        # A real pick on both sides still is one.
        _, conflicts = self.merge(wm.compact_base(base), {"draft_room_table": board("t1", "Ohtani", "Judge")},
                                  {"draft_room_table": board("t2", "Ohtani", "Soto")})
        self.assertTrue(wm.board_conflicted(conflicts))

    def test_base_keeps_only_fingerprints_of_atomic_parts(self) -> None:
        base = wm.compact_base({"draft_room_table": {"table_records": [{"Player": "x"}] * 50},
                                "page_filter_state": {"Live Draft Room": {"live_draft_room": {"big": 1}}}})
        self.assertEqual(set(base["draft_room_table"]), {"__fp__"})
        self.assertEqual(set(base["page_filter_state"]["Live Draft Room"]), {"__fp__"})

    def test_diagnostic_keys_never_raise_a_conflict(self) -> None:
        merged, conflicts = self.merge({"_draft_save_ui_flash": "a"}, {"_draft_save_ui_flash": "b"},
                                       {"_draft_save_ui_flash": "c"})
        self.assertEqual((conflicts, merged["_draft_save_ui_flash"]), ([], "b"))

    def test_tuples_and_lists_are_the_same_value(self) -> None:
        base = pf(**{HIST: {"historical_year_range_filter": [2006, 2012]}})
        merged, conflicts = self.merge(base, pf(**{HIST: {"historical_year_range_filter": (2006, 2012)}}),
                                       pf(**{HIST: {"historical_year_range_filter": [2006, 2012]}}))
        self.assertEqual(conflicts, [])


class ConflictBookkeepingTests(unittest.TestCase):
    def test_open_conflict_pins_saves_to_the_account_side_and_restores_keep_this_side(self) -> None:
        session: dict = {}
        path = ("page_filter_state", HIST, "hist_HR_min")
        local, remote = pf(**{HIST: {"hist_HR_min": 40}}), pf(**{HIST: {"hist_HR_min": 30}})
        wm.note_conflicts(session, "baseball", [path], local, remote)
        self.assertEqual(wm.open_conflicts(session, "baseball")[0]["label"], "Historical Explorer: hist_HR_min")
        outgoing = pf(**{HIST: {"hist_HR_min": 40}})
        wm.pin_conflicts_to_remote(session, "baseball", outgoing, remote)
        self.assertEqual(outgoing["page_filter_state"][HIST]["hist_HR_min"], 30)
        applying = pf(**{HIST: {"hist_HR_min": 30}})
        wm.keep_local_for_conflicts(session, "baseball", applying, local)
        self.assertEqual(applying["page_filter_state"][HIST]["hist_HR_min"], 40)


class StaleRevisionTests(unittest.TestCase):
    def test_a_newer_revision_in_the_same_second_is_stale(self) -> None:
        import suite_cloud_state as scs

        seen = "2026-10-29T12:00:00.100000+00:00"
        self.assertFalse(scs.cloud_write_blocked_by_newer_data(seen, seen))
        self.assertTrue(scs.cloud_write_blocked_by_newer_data(seen, "2026-10-29T12:00:00.900000+00:00"))
        self.assertFalse(scs.cloud_write_blocked_by_newer_data(seen, "2026-10-29T11:59:59+00:00"))


if __name__ == "__main__":
    unittest.main()
