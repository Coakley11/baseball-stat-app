"""Draft Assistant ranking: positional needs, category priorities, and sort modes."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_assistant_ranking import (
    DA_SORT_LABELS,
    MODE_MODEL_VALUE,
    MODE_ROSTER_FIT,
    SORT_MODEL_VALUE,
    SORT_ROSTER_FIT,
    apply_draft_assistant_ranking,
    auto_category_priorities,
    merge_category_priorities,
    open_positions_from_roster,
    order_recommendation_cards,
    ranking_sort_column,
    resolve_action_player_name,
)
from player_action_handoff import queue_unresolved_compare, queue_unresolved_trend, remember_player_action


def _pool() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fullName": "Catcher Speed",
                "Primary Position": "C",
                "Eligible Positions": "C",
                "Expected Fantasy Value": 62,
                "proj_SB": 22,
                "proj_HR": 8,
                "proj_RBI": 50,
                "proj_R": 55,
                "proj_BA": 0.250,
            },
            {
                "fullName": "First Base Power",
                "Primary Position": "1B",
                "Eligible Positions": "1B",
                "Expected Fantasy Value": 74,
                "proj_SB": 2,
                "proj_HR": 32,
                "proj_RBI": 90,
                "proj_R": 80,
                "proj_BA": 0.270,
            },
            {
                "fullName": "Star Outfielder",
                "Primary Position": "OF",
                "Eligible Positions": "OF",
                "Expected Fantasy Value": 96,
                "proj_SB": 6,
                "proj_HR": 38,
                "proj_RBI": 100,
                "proj_R": 95,
                "proj_BA": 0.290,
            },
            {
                "fullName": "Utility Only",
                "Primary Position": "DH",
                "Eligible Positions": "UTIL",
                "Expected Fantasy Value": 80,
                "proj_SB": 4,
                "proj_HR": 24,
                "proj_RBI": 70,
                "proj_R": 68,
                "proj_BA": 0.260,
            },
            {
                "fullName": "Catcher Power",
                "Primary Position": "C",
                "Eligible Positions": "C,1B",
                "Expected Fantasy Value": 70,
                "proj_SB": 1,
                "proj_HR": 28,
                "proj_RBI": 80,
                "proj_R": 60,
                "proj_BA": 0.240,
            },
        ]
    )


class PositionalNeedTests(unittest.TestCase):
    def test_roster_fit_overwhelmingly_prefers_open_c_and_1b(self) -> None:
        ranked = apply_draft_assistant_ranking(
            _pool(),
            mode=MODE_ROSTER_FIT,
            needed_positions=["C", "1B"],
            category_priorities={"SB": "Medium", "HR": "Medium"},
        )
        top = list(ranked.sort_values("Roster Fit Rank Score", ascending=False)["fullName"].head(3))
        self.assertTrue(set(top) <= {"Catcher Speed", "First Base Power", "Catcher Power"})
        self.assertNotIn("Star Outfielder", top)
        star = ranked.loc[ranked["fullName"] == "Star Outfielder"].iloc[0]
        catcher = ranked.loc[ranked["fullName"] == "Catcher Speed"].iloc[0]
        self.assertGreater(float(catcher["Roster Fit Rank Score"]), float(star["Roster Fit Rank Score"]))

    def test_eligibility_not_only_primary_position(self) -> None:
        ranked = apply_draft_assistant_ranking(
            _pool(),
            mode=MODE_ROSTER_FIT,
            needed_positions=["1B"],
            category_priorities={"HR": "High"},
        )
        dual = ranked.loc[ranked["fullName"] == "Catcher Power"].iloc[0]
        self.assertIn("1B", str(dual["Matched Need"]))
        self.assertEqual(float(dual["Fills Required Position"]), 1.0)

    def test_filling_catcher_drops_catcher_only_players(self) -> None:
        before = apply_draft_assistant_ranking(_pool(), mode=MODE_ROSTER_FIT, needed_positions=["C", "1B"])
        after = apply_draft_assistant_ranking(_pool(), mode=MODE_ROSTER_FIT, needed_positions=["1B"])
        only_c = "Catcher Speed"
        self.assertGreater(
            float(before.loc[before["fullName"] == only_c, "Roster Fit Rank Score"].iloc[0]),
            float(after.loc[after["fullName"] == only_c, "Roster Fit Rank Score"].iloc[0]),
        )
        top_after = after.sort_values("Roster Fit Rank Score", ascending=False).iloc[0]["fullName"]
        self.assertIn(top_after, {"First Base Power", "Catcher Power"})


class CategoryPriorityTests(unittest.TestCase):
    def test_stolen_bases_weakness_is_high_without_treating_empty_slots_as_zero(self) -> None:
        roster = pd.DataFrame(
            [
                {"Primary Position": "OF", "proj_SB": 2, "proj_HR": 30, "proj_R": 80, "proj_RBI": 80, "proj_BA": 0.280},
                {"Primary Position": "SS", "proj_SB": 3, "proj_HR": 18, "proj_R": 70, "proj_RBI": 60, "proj_BA": 0.260},
            ]
        )
        pool = _pool()
        pri = auto_category_priorities(roster, pool, ["SB", "HR"], unfilled_hitter_slots=4)
        self.assertEqual(pri["SB"], "High")
        self.assertNotEqual(pri["HR"], "High")

    def test_empty_roster_does_not_invent_a_stolen_base_crisis(self) -> None:
        pri = auto_category_priorities(pd.DataFrame(), _pool(), ["SB", "HR"], unfilled_hitter_slots=8)
        self.assertEqual(pri["SB"], "Medium")

    def test_manual_override_changes_rank_order(self) -> None:
        pool = _pool()
        high_sb = apply_draft_assistant_ranking(
            pool,
            mode=MODE_ROSTER_FIT,
            needed_positions=["C"],
            category_priorities={"SB": "High", "HR": "Low"},
        )
        high_hr = apply_draft_assistant_ranking(
            pool,
            mode=MODE_ROSTER_FIT,
            needed_positions=["C"],
            category_priorities=merge_category_priorities(
                {"SB": "High", "HR": "Low"},
                {"SB": "Low", "HR": "High"},
            ),
        )
        sb_name = "Catcher Speed"
        hr_name = "Catcher Power"
        sb_first = float(high_sb.loc[high_sb["fullName"] == sb_name, "Roster Fit Rank Score"].iloc[0])
        hr_first = float(high_sb.loc[high_sb["fullName"] == hr_name, "Roster Fit Rank Score"].iloc[0])
        sb_second = float(high_hr.loc[high_hr["fullName"] == sb_name, "Roster Fit Rank Score"].iloc[0])
        hr_second = float(high_hr.loc[high_hr["fullName"] == hr_name, "Roster Fit Rank Score"].iloc[0])
        self.assertGreater(sb_first, hr_first)
        self.assertGreater(hr_second, sb_second)

    def test_lower_is_better_era_does_not_reward_a_worse_era(self) -> None:
        pitchers = pd.DataFrame(
            [
                {"fullName": "Good Era", "Primary Position": "P", "Eligible Positions": "P", "Expected Fantasy Value": 70, "proj_ERA": 2.80, "proj_WHIP": 1.05},
                {"fullName": "Bad Era", "Primary Position": "P", "Eligible Positions": "P", "Expected Fantasy Value": 70, "proj_ERA": 5.40, "proj_WHIP": 1.45},
            ]
        )
        ranked = apply_draft_assistant_ranking(
            pitchers,
            mode=MODE_MODEL_VALUE,
            needed_positions=["P"],
            category_priorities={"ERA": "High", "WHIP": "High"},
        )
        good = float(ranked.loc[ranked["fullName"] == "Good Era", "Category Improvement Score"].iloc[0])
        bad = float(ranked.loc[ranked["fullName"] == "Bad Era", "Category Improvement Score"].iloc[0])
        self.assertGreater(good, bad)


class SortModeTests(unittest.TestCase):
    def test_roster_fit_and_model_value_are_different_orders(self) -> None:
        ranked = apply_draft_assistant_ranking(
            _pool(),
            mode=MODE_ROSTER_FIT,
            needed_positions=["C", "1B"],
            category_priorities={"SB": "High", "HR": "Low"},
        )
        fit_order = list(ranked.sort_values("Roster Fit Rank Score", ascending=False)["fullName"])
        model_order = list(ranked.sort_values("Model Value Score", ascending=False)["fullName"])
        self.assertNotEqual(fit_order, model_order)
        self.assertEqual(model_order[0], "Star Outfielder")
        self.assertIn(fit_order[0], {"Catcher Speed", "First Base Power", "Catcher Power"})
        self.assertNotEqual(
            ranking_sort_column(SORT_ROSTER_FIT)[0],
            ranking_sort_column(SORT_MODEL_VALUE)[0],
        )

    def test_reason_mentions_position_and_category(self) -> None:
        ranked = apply_draft_assistant_ranking(
            _pool(),
            mode=MODE_ROSTER_FIT,
            needed_positions=["C"],
            category_priorities={"SB": "High"},
        )
        reason = str(ranked.loc[ranked["fullName"] == "Catcher Speed", "Why this pick"].iloc[0])
        self.assertIn("fills C", reason)
        self.assertIn("improves SB", reason)
        self.assertTrue(reason.startswith("Strong roster fit"))


class EverySortOptionTests(unittest.TestCase):
    def test_each_dropdown_option_reorders_cards_and_renumbers(self) -> None:
        pool = _pool().copy()
        pool["Decision Score"] = [0.40, 0.55, 0.99, 0.20, 0.61]
        pool["Player Grade"] = [61, 88, 70, 95, 64]
        pool["Model Rank"] = [40, 8, 2, 15, 22]
        pool["Market Rank"] = [90, 12, 4, 30, 18]
        pool["Position Scarcity Score"] = [0.9, 0.2, 0.1, 0.4, 0.7]
        scored = apply_draft_assistant_ranking(
            pool,
            mode=MODE_ROSTER_FIT,
            needed_positions=["C", "1B"],
            category_priorities={"SB": "High", "HR": "Low"},
        )
        orders = {}
        for label in DA_SORT_LABELS:
            ordered = order_recommendation_cards(scored, label)
            names = list(ordered["fullName"])
            ranks = list(ordered["Card Rank"])
            self.assertEqual(ranks, list(range(1, len(names) + 1)))
            self.assertEqual(len(names), len(set(names)))
            orders[label] = tuple(names)
        self.assertEqual(len(set(orders.values())), len(DA_SORT_LABELS))
        fit = order_recommendation_cards(scored, "Roster Fit")
        self.assertIn(fit.iloc[0]["fullName"], {"Catcher Speed", "First Base Power", "Catcher Power"})
        self.assertEqual(int(fit.iloc[0]["Card Rank"]), 1)
        grade = order_recommendation_cards(scored, "Player Grade")
        self.assertEqual(grade.iloc[0]["fullName"], "Utility Only")
        model_rank = order_recommendation_cards(scored, "Model Rank")
        self.assertEqual(model_rank.iloc[0]["fullName"], "Star Outfielder")
        market = order_recommendation_cards(scored, "Market Rank")
        self.assertEqual(market.iloc[0]["fullName"], "Star Outfielder")

    def test_filled_starters_do_not_bury_the_best_player(self) -> None:
        ranked = apply_draft_assistant_ranking(
            _pool(),
            mode=MODE_ROSTER_FIT,
            needed_positions=[],
            category_priorities={"SB": "Low", "HR": "Low"},
        )
        ordered = order_recommendation_cards(ranked, "Roster Fit")
        self.assertEqual(ordered.iloc[0]["fullName"], "Star Outfielder")


class RosterRequirementTests(unittest.TestCase):
    def test_open_slots_ignore_bench_and_filled_positions(self) -> None:
        roster = pd.DataFrame(
            [{"Primary Position": "OF"}, {"Primary Position": "OF"}, {"Primary Position": "SS"}]
        )
        open_pos = open_positions_from_roster(
            roster,
            {"C": 1, "1B": 1, "2B": 1, "SS": 1, "OF": 3, "BN": 5},
        )
        self.assertIn("C", open_pos)
        self.assertIn("1B", open_pos)
        self.assertNotIn("SS", open_pos)
        self.assertNotIn("BN", open_pos)
        self.assertEqual(open_pos.count("OF"), 1)


class WaiverHandoffTests(unittest.TestCase):
    def test_name_resolution_ignores_accents_and_suffixes(self) -> None:
        label_map = {"Jose Ramirez (ramij01)": "ramij01", "Juan Soto (sotoj01)": "sotoj01"}
        self.assertEqual(resolve_action_player_name("José Ramírez Jr.", label_map), "Jose Ramirez (ramij01)")
        self.assertIsNone(resolve_action_player_name("Nobody", label_map))

    def test_unresolved_trend_and_compare_keep_the_player_and_explain(self) -> None:
        session: dict[str, str | list[str]] = {}
        remember_player_action(session, "Elly De La Cruz", "Send to Trend Page")
        page = queue_unresolved_trend(session, "Elly De La Cruz", "Not enough seasons for a trend chart.")
        self.assertEqual(page, "Trend Value")
        self.assertEqual(session["pending_trend_player"], "Elly De La Cruz")
        self.assertIn("Not enough seasons", session["trend_unavailable_notice"])
        page = queue_unresolved_compare(session, "Elly De La Cruz", "Could not match Elly De La Cruz.")
        self.assertEqual(page, "Comparison Tool")
        self.assertEqual(session["pending_compare_players"], ["Elly De La Cruz"])
        self.assertEqual(session["waiver_action_player"], "Elly De La Cruz")


if __name__ == "__main__":
    unittest.main()
