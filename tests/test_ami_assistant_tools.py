"""AMI tools return exactly what the Baseball Explorer pages calculate (real Lahman data).

Parity tests run the pages' own helper functions (compiled from streamlit_app.py) and the
pages' step order (pinned by source checks), then compare with the AMI tool output.
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from ami_assistant.data import load_standalone_dataset, load_standalone_frames
from ami_assistant.tools import REGISTRY
from ami_assistant.tools import registry as codes
from ami_assistant.tools.value import TREND_STATS, page_trend_table, valuation_pool, window_rows
from baseball_history import add_rate_stats
from leaderboard_aggregation import aggregate_leaderboard_career_totals, filter_yearly_for_leaderboards
from rate_stat_qualification import qualified_ab, season_lengths
from tests.ami_assistant_fixtures import monolith_functions, page_section
from valuation_scores import VALUATION_MIN_AB, add_valuation_scores, valuation_hitter_pool

WINDOW_COLS = ("G", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "HBP", "SF")


class RealDataCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ds = load_standalone_dataset()
        cls.yearly = cls.ds.yearly

    def call(self, name: str, **args):
        return REGISTRY.call(name, args, dataset=self.ds, session={})


class PageSourceStillMatchesTests(unittest.TestCase):
    """If a page changes its pipeline, these fail and the AMI tool must follow."""

    def test_valuation_page_pipeline(self) -> None:
        sec = page_section("Valuation")
        steps = [
            'recent_data_value = yearly_df[yearly_df["yearID"].isin(recent_years_value)].copy().sort_values(["playerID", "yearID"])',
            "agg_value = aggregate_recent_player_totals(",
            'agg_value = valuation_hitter_pool(agg_value[agg_value["G"] >= min_g_value])',
            "trend_value = compute_player_trend_table(",
            'valuation_df = agg_value.merge(trend_value, on="playerID", how="left")',
            "valuation_df = add_latest_and_projection_columns(valuation_df, recent_data_value)",
            "add_valuation_scores(valuation_df, w_current, w_trend)",
        ]
        positions = [sec.index(s) for s in steps]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('validate_number_state("value_min_g", 50', sec)
        self.assertIn('validate_state_option("value_lag", _value_lag_options, 3)', sec)

    def test_trend_value_page_pipeline(self) -> None:
        sec = page_section("Trend Value")
        for s in ("trend_table = compute_player_trend_table(", 'agg_trend = agg_trend[agg_trend["G"] >= min_g_trend].copy()',
                  'validate_number_state("trend_min_g", 50'):
            self.assertIn(s, sec)

    def test_leaderboards_page_pipeline(self) -> None:
        sec = page_section("Leaderboards")
        steps = [
            "filtered_leaders = filter_yearly_for_leaderboards(yearly_df, range_leaders)",
            "leaderboard = aggregate_leaderboard_career_totals(filtered_leaders)",
            "leaderboard = add_rate_stats(leaderboard)",
            "qualification=_qualified_ab(SEASON_GAME_COUNTS, range_leaders, span=True)",
            "leaderboard = safe_round_rate_stats(leaderboard)",
            'leaderboard_sorted = leaderboard.sort_values(sort_stat_leaders, ascending=False, na_position="last")',
        ]
        positions = [sec.index(s) for s in steps]
        self.assertEqual(positions, sorted(positions))

    def test_career_totals_page_pipeline(self) -> None:
        sec = page_section("Career Totals")
        for s in ('filtered_career = filtered_career[filtered_career[position_source_col].isin(pos_filter_career)]',
                  'career_totals = filtered_career.groupby(["playerID", "fullName", "bats"], as_index=False, dropna=False)[stat_cols_career].sum()',
                  "qualification=_qualified_ab(SEASON_GAME_COUNTS, range_career, span=True)",
                  'position_source_col = "careerPrimaryPos" if position_filter_mode == "Career Primary Position" else "primaryPos"'):
            self.assertIn(s, sec)


def _pool_steps(page: str, names: tuple[str, ...]) -> list[str]:
    """Every statement on the page that reassigns one of the pool frames (first line only)."""
    import re

    pat = re.compile(r"^\s*(?:%s)\s+=\s.*$|^\s*add_valuation_scores\(.*$" % "|".join(names), re.M)
    return [m.group(0).strip() for m in pat.finditer(page_section(page))]


# How ami_assistant/tools/value.py treats each page step. "mirrored" = same computation;
# "not applied" = user-specific option AMI states in its answer instead of applying.
VALUATION_STEPS = {
    'recent_data_value = yearly_df[yearly_df["yearID"].isin(recent_years_value)].copy().sort_values(["playerID", "yearID"])': "mirrored",
    'recent_data_value = recent_data_value[~recent_data_value["fullName"].astype(str).isin(set(value_drafted_names))].copy()': "not applied (Draft Room sync)",
    "agg_value = aggregate_recent_player_totals(": "mirrored",
    'agg_value = valuation_hitter_pool(agg_value[agg_value["G"] >= min_g_value])': "mirrored (valuation_scores.valuation_hitter_pool, Phase D7)",
    'agg_value = apply_stat_min_filters(agg_value, "value", on_change=valuation_filter_changed)': "mirrored at defaults (no minimums)",
    "trend_value = compute_player_trend_table(": "mirrored",
    'valuation_df = agg_value.merge(trend_value, on="playerID", how="left")': "mirrored",
    "valuation_df = add_latest_and_projection_columns(valuation_df, recent_data_value)": "mirrored (zero-filled trends)",
    "valuation_df = merge_canonical_projections(valuation_df, _canonical_value_pool)": "irrelevant to scores (proj_* columns)",
    "valuation_df = attach_fantasy_position_columns(valuation_df, recent_data_value)": "irrelevant to scores",
    "valuation_df = filter_players_by_fantasy_position(valuation_df, value_position_filter)": "not applied (position filter)",
    "add_valuation_scores(valuation_df, w_current, w_trend)": "mirrored",
    "valuation_df = apply_research_recommendation_adjustments(": "not applied (roster-need boosts)",
    "valuation_df = safe_round_rate_stats(valuation_df)": "display only",
}
TREND_STEPS = {
    'recent_baseline_trend = yearly_df[yearly_df["yearID"].isin(recent_years_trend)].copy().sort_values(["playerID", "yearID"])': "mirrored",
    "recent_data_trend = recent_baseline_trend.copy()": "mirrored",
    'recent_data_trend = recent_data_trend[~recent_data_trend["fullName"].astype(str).isin(set(trend_drafted_names))].copy()': "not applied (Draft Room sync)",
    "agg_trend = aggregate_recent_player_totals(": "mirrored",
    'agg_trend = agg_trend[agg_trend["G"] >= min_g_trend].copy()': "mirrored",
    'agg_trend = apply_stat_min_filters(agg_trend, "trend")': "mirrored at defaults (no minimums)",
    "trend_table = compute_player_trend_table(": "mirrored",
    'trend_value_df = agg_trend.merge(trend_table, on="playerID", how="left")': "mirrored",
    "trend_value_df = add_latest_and_projection_columns(trend_value_df, recent_data_trend)": "page zero-fills; AMI reports blank (stated)",
    "trend_value_df = merge_canonical_projections(trend_value_df, _canonical_trend_pool)": "irrelevant to slopes",
    "trend_value_df = apply_research_recommendation_adjustments(": "not applied (sort only)",
    "trend_value_df = attach_fantasy_position_columns(trend_value_df, recent_data_trend)": "irrelevant to slopes",
    "trend_value_df = filter_players_by_fantasy_position(trend_value_df, trend_position_filter)": "not applied (position filter)",
}


class PagePipelineStrictPinTests(unittest.TestCase):
    """Strict tripwire: a new, removed or reordered pool step fails here, naming the step, so
    the AMI tool is updated deliberately (e.g. Phase D7's valuation_hitter_pool)."""

    def _check(self, page: str, names: tuple[str, ...], expected: dict[str, str]) -> None:
        actual = _pool_steps(page, names)
        unknown = [s for s in actual if s not in expected]
        self.assertEqual(unknown, [], f"{page} has pipeline steps AMI doesn't know about; update ami_assistant/tools/value.py")
        self.assertEqual(actual, list(expected), f"{page} pipeline steps were removed or reordered")

    def test_valuation_pipeline_is_exactly_known(self) -> None:
        self._check("Valuation", ("recent_data_value", "agg_value", "trend_value", "valuation_df"), VALUATION_STEPS)

    def test_trend_value_pipeline_is_exactly_known(self) -> None:
        self._check("Trend Value", ("recent_baseline_trend", "recent_data_trend", "agg_trend", "trend_table", "trend_value_df"),
                    TREND_STEPS)


class TrendAndValuationParityTests(RealDataCase):
    def test_trend_table_equals_the_page_function(self) -> None:
        page = monolith_functions("compute_player_trend_table")["compute_player_trend_table"]
        years = list(range(self.ds.latest_season - 2, self.ds.latest_season + 1))
        recent = window_rows(self.ds, years)
        expected = page(recent, TREND_STATS)
        pd.testing.assert_frame_equal(page_trend_table(recent).reset_index(drop=True), expected.reset_index(drop=True))

    def test_valuation_scores_equal_the_page_pipeline(self) -> None:
        fns = monolith_functions("aggregate_recent_player_totals", "compute_player_trend_table", "add_latest_and_projection_columns")
        for window, min_g, w_c, w_t in ((3, 50, 1.0, 1.0), (5, 100, 2.0, 1.0)):
            years = list(range(self.ds.latest_season - window + 1, self.ds.latest_season + 1))
            recent = self.yearly[self.yearly["yearID"].isin(years)].copy().sort_values(["playerID", "yearID"])
            agg = fns["aggregate_recent_player_totals"](recent, WINDOW_COLS)
            agg = valuation_hitter_pool(agg[agg["G"] >= min_g])  # the page's own step (Phase D7)
            trend = fns["compute_player_trend_table"](recent, TREND_STATS)
            page = fns["add_latest_and_projection_columns"](agg.merge(trend, on="playerID", how="left"), recent)
            add_valuation_scores(page, w_c, w_t)
            ami, _ = valuation_pool(self.ds, window, min_g, w_c, w_t)
            merged = page[["playerID", "Valuation_Score", "Perf_Score", "Trend_Score"]].merge(
                ami[["playerID", "Valuation_Score", "Perf_Score", "Trend_Score"]], on="playerID", suffixes=("_page", "_ami"))
            self.assertEqual(len(merged), len(page))
            self.assertEqual(len(merged), len(ami))
            for col in ("Valuation_Score", "Perf_Score", "Trend_Score"):
                np.testing.assert_allclose(merged[f"{col}_page"], merged[f"{col}_ami"], rtol=0, atol=1e-12)
            # Rank parity: the page sorts by Valuation_Score; AMI's rank is the same ordering.
            page_rank = page.set_index("playerID")["Valuation_Score"].rank(ascending=False, method="min").astype(int)
            pd.testing.assert_series_equal(ami.set_index("playerID")["rank"].sort_index(), page_rank.sort_index(),
                                           check_names=False)

    def test_hitter_pool_excludes_pitchers_and_keeps_two_way_ohtani(self) -> None:
        from ami_assistant.tools.value import window_pool

        years = list(range(self.ds.latest_season - 2, self.ds.latest_season + 1))
        before = window_pool(window_rows(self.ds, years), 50)
        dropped = set(before.loc[before["AB"] < VALUATION_MIN_AB, "playerID"])
        self.assertGreater(len(dropped), 100)  # the D7 problem was real: hundreds of relievers
        ami, _ = valuation_pool(self.ds, 3, 50, 1.0, 1.0)
        self.assertFalse(dropped & set(ami["playerID"]))
        self.assertTrue((ami["AB"] >= VALUATION_MIN_AB).all())
        self.assertIn("ohtansh01", set(ami["playerID"]))
        pitcher = sorted(dropped)[0]
        res = self.call("get_player_valuation", player_id=pitcher)
        self.assertEqual(res.error_code, codes.NOT_IN_POOL)
        self.assertIn("at-bats", res.message)
        self.assertTrue(self.call("get_player_valuation", player_id="ohtansh01").ok)

    def test_player_valuation_reports_the_pool_row(self) -> None:
        res = self.call("get_player_valuation", player_id="judgeaa01")
        self.assertTrue(res.ok, res.message)
        pool, _ = valuation_pool(self.ds, 3, 50, 1.0, 1.0)
        row = pool[pool["playerID"] == "judgeaa01"].iloc[0]
        v = res.data["valuation"]
        self.assertAlmostEqual(v["valuation_score"], round(row["Valuation_Score"] * 100, 3))
        self.assertEqual(v["rank"], int((pool["Valuation_Score"] > row["Valuation_Score"]).sum()) + 1)
        self.assertEqual(res.data["pool_size"], len(pool))

    def test_player_trend_slopes_and_percentiles(self) -> None:
        res = self.call("get_player_trends", player_id="bettsmo01")
        self.assertTrue(res.ok, res.message)
        years = list(range(self.ds.latest_season - 2, self.ds.latest_season + 1))
        table = page_trend_table(window_rows(self.ds, years))
        hr = next(t for t in res.data["trends"] if t["stat"] == "HR")
        self.assertAlmostEqual(hr["slope_per_season"], round(float(table.set_index("playerID").at["bettsmo01", "HR_trend"]), 3))
        seasons = self.ds.player_rows("bettsmo01")
        self.assertEqual([s["value"] for s in hr["by_season"]],
                         [int(v) for v in seasons[seasons["yearID"].isin(years)]["HR"]])
        self.assertTrue(0 <= hr["percentile_in_pool"] <= 100)


class StatToolAccuracyTests(RealDataCase):
    def test_profile_totals_are_the_season_sums(self) -> None:
        res = self.call("get_player_profile", player_id="ruthba01")
        rows = self.ds.player_rows("ruthba01")
        self.assertEqual(res.data["career_totals"]["HR"], int(rows["HR"].sum()))
        self.assertEqual(res.data["career_totals"]["HR"], 714)
        self.assertTrue(res.data["hall_of_famer"])
        best = res.data["best_seasons_by_ops"][0]
        top = rows[rows["AB"] >= rows["yearID"].map(lambda y: qualified_ab(self.ds.season_games, (y, y), span=False)["value"])]
        self.assertEqual(best["season"], int(top.sort_values("OPS", ascending=False).iloc[0]["yearID"]))

    def test_season_lookup(self) -> None:
        res = self.call("get_player_seasons", player_id="judgeaa01", year_range=[2022, 2022])
        self.assertEqual(res.data["seasons"][0]["HR"], 62)

    def test_comparison_sums_the_range_and_recomputes_rates(self) -> None:
        res = self.call("compare_players", player_ids=["judgeaa01", "sotoju01"], year_range=[2022, 2025])
        self.assertTrue(res.ok)
        for p in res.data["players"]:
            rows = self.ds.player_rows(p["player"]["player_id"])
            rows = rows[rows["yearID"].between(2022, 2025)]
            totals = add_rate_stats(rows[list(WINDOW_COLS)].sum().to_frame().T).iloc[0]
            self.assertEqual(p["totals"]["HR"], int(totals["HR"]))
            self.assertAlmostEqual(p["totals"]["OPS"], round(float(totals["OPS"]), 3))
        ops = res.data["leaders"]["OPS"]
        self.assertEqual(ops["leader"], max(ops["values"], key=ops["values"].get))

    def test_leaderboard_equals_the_leaderboards_page(self) -> None:
        fns = monolith_functions("safe_round_rate_stats")
        rng = (2020, self.ds.latest_season)
        board = add_rate_stats(aggregate_leaderboard_career_totals(filter_yearly_for_leaderboards(self.yearly, rng)))
        qual = qualified_ab(season_lengths(self.yearly), rng, span=True)["value"]
        board = board[board["AB"].fillna(-np.inf) >= qual]
        board = fns["safe_round_rate_stats"](board).sort_values("OPS", ascending=False, na_position="last")
        res = self.call("get_leaderboard", stat="OPS", year_range=list(rng), top_n=25)
        self.assertEqual([r["player_id"] for r in res.data["rows"]], board["playerID"].head(25).tolist())
        self.assertEqual(res.data["min_ab"], qual)

    def test_position_leaderboard_equals_career_totals_on_stint_rows(self) -> None:
        batting = load_standalone_frames()[0]
        rng = (2021, self.ds.latest_season)
        rows = batting[(batting["yearID"] >= rng[0]) & (batting["yearID"] <= rng[1])]
        rows = rows[rows["careerPrimaryPos"].isin(["SS"])]
        cols = ["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "HBP", "SF", "G"]
        page = add_rate_stats(rows.groupby(["playerID", "fullName", "bats"], as_index=False, dropna=False)[cols].sum())
        page = page[page["AB"].fillna(-np.inf) >= qualified_ab(self.ds.season_games, rng, span=True)["value"]]
        page = monolith_functions("safe_round_rate_stats")["safe_round_rate_stats"](page)
        page = page.sort_values("OPS", ascending=False)
        res = self.call("get_leaderboard", stat="OPS", year_range=list(rng), position="SS", top_n=10)
        self.assertEqual([r["player_id"] for r in res.data["rows"]], page["playerID"].head(10).tolist())
        self.assertEqual(res.data["source_page"], "Career Totals")

    def test_counting_stat_leaderboard_has_no_minimum(self) -> None:
        res = self.call("get_leaderboard", stat="HR", year_range=[1927, 1927], top_n=1)
        self.assertEqual(res.data["min_ab"], 0)
        self.assertEqual(res.data["rows"][0]["player"], "Babe Ruth")
        self.assertEqual(res.data["rows"][0]["HR"], 60)


class FailureStateTests(RealDataCase):
    def test_unknown_player(self) -> None:
        res = self.call("get_player_profile", player_id="Zzyzx Qwertyuiop")
        self.assertEqual(res.error_code, codes.UNKNOWN_PLAYER)

    def test_ambiguous_player(self) -> None:
        res = self.call("get_player_profile", player_id="Frank Thomas")
        self.assertEqual(res.error_code, codes.AMBIGUOUS_PLAYER)
        self.assertGreaterEqual(len(res.data["candidates"]), 2)

    def test_unavailable_season(self) -> None:
        self.assertEqual(self.call("get_player_seasons", player_id="sotoju01", year_range=[1990, 1995]).error_code,
                         codes.UNAVAILABLE_SEASON)
        self.assertEqual(self.call("get_leaderboard", stat="HR", year_range=[2031, 2032]).error_code, codes.UNAVAILABLE_SEASON)

    def test_insufficient_trend_history(self) -> None:
        latest = self.ds.latest_season
        rookies = self.ds.players[(self.ds.players["first_season"] == latest) & (self.ds.players["career_g"] >= 50)]
        res = self.call("get_player_trends", player_id=rookies.index[0])
        self.assertEqual(res.error_code, codes.INSUFFICIENT_HISTORY)

    def test_retired_player_is_not_in_the_valuation_pool(self) -> None:
        res = self.call("get_player_valuation", player_id="ruthba01")
        self.assertEqual(res.error_code, codes.NOT_IN_POOL)

    def test_missing_draft_context_and_league(self) -> None:
        self.assertEqual(self.call("get_draft_recommendations").error_code, codes.MISSING_DRAFT_CONTEXT)
        self.assertEqual(self.call("get_team_needs").error_code, codes.MISSING_DRAFT_CONTEXT)
        league = self.call("get_active_league")  # wired to fantasy_read_api since the Phase D reconciliation
        self.assertEqual(league.error_code, codes.MISSING_ACTIVE_LEAGUE)
        self.assertIn("Saved Draft Library", league.message)


if __name__ == "__main__":
    unittest.main()
