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

    # --- the queue is an ordered list: removals, reorders and additions from either device ---

    def q(self, base, local, remote, key="draft_queue"):
        merged, conflicts = self.merge({key: base}, {key: local}, {key: remote})
        return merged[key], conflicts

    def test_a_removal_on_the_phone_is_not_undone_by_the_dells_older_copy(self) -> None:
        self.assertEqual(self.q(["A", "B", "X"], ["A", "B", "X"], ["A", "B"]), (["A", "B"], []))
        self.assertEqual(self.q(["A", "B", "X"], ["A", "B"], ["A", "B", "X"]), (["A", "B"], []))  # and the reverse

    def test_a_reorder_on_one_device_survives(self) -> None:
        moved_to_top = ["C", "A", "B"]
        self.assertEqual(self.q(["A", "B", "C"], ["A", "B", "C"], moved_to_top), (moved_to_top, []))
        self.assertEqual(self.q(["A", "B", "C"], moved_to_top, ["A", "B", "C"]), (moved_to_top, []))

    def test_a_reorder_here_and_an_addition_there_are_both_kept(self) -> None:
        merged, conflicts = self.q(["A", "B", "C"], ["B", "A", "C"], ["A", "B", "C", "D"])   # move up / add
        self.assertEqual((merged, conflicts), (["B", "A", "C", "D"], []))
        merged, _ = self.q(["A", "B", "C"], ["A", "C", "B"], ["A", "B", "N", "C"])           # inserted before C
        self.assertEqual(merged, ["A", "N", "C", "B"])

    def test_a_removal_there_and_a_reorder_here_combine_without_duplicates(self) -> None:
        merged, conflicts = self.q(["A", "B", "C", "D"], ["D", "A", "B", "C"], ["A", "C", "D"])
        self.assertEqual((merged, conflicts), (["D", "A", "C"], []))
        self.assertEqual(len(merged), len(set(merged)))

    def test_moving_a_player_the_other_device_removed_does_not_bring_him_back(self) -> None:
        merged, _ = self.q(["A", "B", "X"], ["X", "A", "B"], ["A", "B"])
        self.assertEqual(merged, ["A", "B"])

    def test_both_devices_reordering_differently_is_a_conflict_not_a_guess(self) -> None:
        merged, conflicts = self.q(["A", "B", "C"], ["C", "B", "A"], ["B", "A", "C"])
        self.assertEqual(conflicts, [("draft_queue",)])
        self.assertEqual(merged, ["B", "A", "C"])          # the account keeps its order meanwhile
        merged, conflicts = self.q(["A", "B", "C"], ["C", "A", "B"], ["C", "A", "B"])
        self.assertEqual((merged, conflicts), (["C", "A", "B"], []))  # the same move on both is not one

    def test_both_devices_adding_the_same_player_keeps_one(self) -> None:
        self.assertEqual(self.q(["A"], ["A", "Z"], ["A", "Z"])[0], ["A", "Z"])
        self.assertEqual(self.q(["A"], ["A", "Z", "Y"], ["A", "Y"])[0], ["A", "Z", "Y"])

    def test_an_emptied_queue_is_a_real_edit(self) -> None:
        self.assertEqual(self.q(["A", "B"], [], ["A", "B"]), ([], []))
        self.assertEqual(self.q(["A", "B"], [], ["A", "B", "C"])[0], ["C"])   # the phone's new add survives

    def test_watchlists_follow_the_same_rules(self) -> None:
        for key in ("watchlist_focus", "watchlist_favorites"):
            self.assertEqual(self.q(["A", "B"], ["A", "B"], ["B"], key=key)[0], ["B"])
            self.assertEqual(self.q(["A", "B"], ["B", "A"], ["A", "B", "C"], key=key)[0], ["B", "A", "C"])
        merged, _ = self.merge({"draft_state": {"queue": ["A", "X"]}}, {"draft_state": {"queue": ["A", "X"]}},
                               {"draft_state": {"queue": ["A"]}})
        self.assertEqual(merged["draft_state"]["queue"], ["A"])            # the canonical copy too

    def test_view_history_and_the_board_epoch_never_raise_a_conflict(self) -> None:
        merged, conflicts = self.merge({"workflow_recently_viewed": ["A"], "_simulator_board_epoch": 1},
                                       {"workflow_recently_viewed": ["B", "A"], "_simulator_board_epoch": 2},
                                       {"workflow_recently_viewed": ["C", "A"], "_simulator_board_epoch": 3})
        self.assertEqual(conflicts, [])
        self.assertEqual((merged["workflow_recently_viewed"], merged["_simulator_board_epoch"]), (["B", "A"], 3))

    # --- account preferences carried in the workspace: leagues and explicit choices ---

    def leagues(self, active="L1", **contexts):
        return {"fantasy_league_context_state": {"schema_version": 1, "active_league_context_id": active,
                                                 "contexts": contexts, "deleted_context_ids": []}}

    def test_a_filter_on_one_device_never_resets_the_active_league_on_the_other(self) -> None:
        base = {**self.leagues("L1", L1={"name": "A"}, L2={"name": "B"}), **pf(**{HIST: {"hist_HR_min": 0}})}
        local = {**self.leagues("L1", L1={"name": "A"}, L2={"name": "B"}), **pf(**{HIST: {"hist_HR_min": 40}})}
        remote = {**self.leagues("L2", L1={"name": "A"}, L2={"name": "B"}), **pf(**{HIST: {"hist_HR_min": 0}})}
        merged, conflicts = self.merge(base, local, remote)
        self.assertEqual(conflicts, [])
        self.assertEqual(merged["fantasy_league_context_state"]["active_league_context_id"], "L2")
        self.assertEqual(merged["page_filter_state"][HIST]["hist_HR_min"], 40)

    def test_editing_one_league_here_and_switching_leagues_there_are_both_kept(self) -> None:
        base = self.leagues("L1", L1={"teams": 10}, L2={"teams": 12})
        local = self.leagues("L1", L1={"teams": 14}, L2={"teams": 12})      # Dell edits league 1
        remote = self.leagues("L2", L1={"teams": 10}, L2={"teams": 12})     # phone switches to league 2
        merged, conflicts = self.merge(base, local, remote)
        store = merged["fantasy_league_context_state"]
        self.assertEqual(conflicts, [])
        self.assertEqual((store["active_league_context_id"], store["contexts"]["L1"]["teams"]), ("L2", 14))

    def test_the_same_league_edited_on_both_is_a_conflict_on_that_league_only(self) -> None:
        base = self.leagues("L1", L1={"teams": 10, "scoring": "roto"}, L2={"teams": 12})
        local = self.leagues("L1", L1={"teams": 14, "scoring": "roto"}, L2={"teams": 12})
        remote = self.leagues("L1", L1={"teams": 10, "scoring": "points"}, L2={"teams": 16})
        merged, conflicts = self.merge(base, local, remote)
        self.assertEqual(conflicts, [("fantasy_league_context_state", "contexts", "L1")])
        self.assertEqual(merged["fantasy_league_context_state"]["contexts"]["L2"]["teams"], 16)
        self.assertEqual(wm.conflict_label(conflicts[0]), "League settings (L1)")

    def test_explicit_choices_are_never_mixed_and_the_later_one_wins(self) -> None:
        base = {"fantasy_source_override_selection": {"override_kind": "none", "selected_at": "2026-10-29T10:00:00Z", "local_seq": 1}}
        local = {"fantasy_source_override_selection": {"override_kind": "simulator_board", "override_id": "simulator",
                                                       "selected_at": "2026-10-29T10:05:00Z", "local_seq": 2}}
        remote = {"fantasy_source_override_selection": {"override_kind": "live_draft_room", "override_id": "ROOM9",
                                                        "selected_at": "2026-10-29T10:07:00Z", "local_seq": 2}}
        merged, conflicts = self.merge(base, local, remote)
        self.assertEqual(conflicts, [])
        self.assertEqual(merged["fantasy_source_override_selection"], remote["fantasy_source_override_selection"])
        local["fantasy_source_override_selection"]["selected_at"] = "2026-10-29T10:09:00Z"
        merged, _ = self.merge(base, local, remote)
        self.assertEqual(merged["fantasy_source_override_selection"], local["fantasy_source_override_selection"])

    def test_a_league_deleted_on_one_device_stays_deleted(self) -> None:
        base = self.leagues("L1", L1={"teams": 10}, L2={"teams": 12})
        local = self.leagues("L1", L1={"teams": 10})
        local["fantasy_league_context_state"]["deleted_context_ids"] = ["L2"]
        remote = {**self.leagues("L1", L1={"teams": 10}, L2={"teams": 12}), **pf(**{HIST: {"hist_HR_min": 5}})}
        merged, conflicts = self.merge(base, local, remote)
        store = merged["fantasy_league_context_state"]
        self.assertEqual(conflicts, [])
        self.assertNotIn("L2", store["contexts"])
        self.assertEqual(store["deleted_context_ids"], ["L2"])

    # --- Saved Draft Library: per saved draft ---

    def lib(self, *entries):
        return {"draft_archive_teams": [dict(draft_id=d, **fields) for d, fields in entries]}

    def test_a_draft_saved_on_each_device_keeps_both(self) -> None:
        base = self.lib(("d1", {"draft_name": "Home league"}))
        local = self.lib(("d1", {"draft_name": "Home league"}), ("d2", {"draft_name": "Dell mock"}))
        remote = self.lib(("d1", {"draft_name": "Home league"}), ("d3", {"draft_name": "Phone mock"}))
        merged, conflicts = self.merge(base, local, remote)
        self.assertEqual(conflicts, [])
        self.assertEqual([e["draft_id"] for e in merged["draft_archive_teams"]], ["d1", "d3", "d2"])

    def test_a_draft_deleted_on_one_device_stays_deleted(self) -> None:
        base = self.lib(("d1", {"n": 1}), ("d2", {"n": 2}))
        merged, conflicts = self.merge(base, self.lib(("d1", {"n": 1})), self.lib(("d1", {"n": 1}), ("d2", {"n": 2}), ("d3", {"n": 3})))
        self.assertEqual(([e["draft_id"] for e in merged["draft_archive_teams"]], conflicts), (["d1", "d3"], []))

    def test_one_draft_edited_on_both_is_a_conflict_on_that_draft_and_the_rest_merge(self) -> None:
        base = self.lib(("d1", {"draft_name": "A"}))
        local = self.lib(("d1", {"draft_name": "A (Dell)"}), ("d2", {"draft_name": "new here"}))
        remote = self.lib(("d1", {"draft_name": "A (phone)"}), ("d3", {"draft_name": "new there"}))
        merged, conflicts = self.merge(base, local, remote)
        path = ("draft_archive_teams", "@d1")
        self.assertEqual(conflicts, [path])
        self.assertEqual({e["draft_id"] for e in merged["draft_archive_teams"]}, {"d1", "d2", "d3"})
        self.assertEqual(wm.get_path(merged, path)["draft_name"], "A (phone)")       # the account's, meanwhile
        session: dict = {}
        wm.note_conflicts(session, "baseball", conflicts, local, remote)
        wm.keep_local_for_conflicts(session, "baseball", merged, local)               # this device shows its own
        self.assertEqual(wm.get_path(merged, path)["draft_name"], "A (Dell)")
        self.assertEqual({e["draft_id"] for e in merged["draft_archive_teams"]}, {"d1", "d2", "d3"})
        self.assertEqual(wm.conflict_label(path), "Saved Draft Library: a draft (d1)")

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
