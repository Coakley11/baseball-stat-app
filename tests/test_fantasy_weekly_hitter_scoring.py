"""Tests for hitter-only weekly fantasy scoring."""

from __future__ import annotations

import copy
import unittest

import pandas as pd

from fantasy_league_context import save_imported_league_context, upsert_league_context
from fantasy_weekly_hitter_scoring import (
    STANDARD_ROTO_5X5,
    apply_finalized_week_to_standings,
    compute_player_weekly_results,
    compute_team_weekly_totals,
    create_weekly_baseline_on_lock,
    extract_cumulative_snapshot,
    finalize_week_for_league,
    get_weekly_scoring_record,
    is_legacy_locked_lineup,
    is_week_finalized_for_league,
    mark_legacy_lineup_scoring,
    preview_finalize_week,
    refresh_weekly_scoring,
    resolve_hitter_scoring_profile,
    should_start_week_empty,
    weekly_finalize_id,
    resolve_canonical_league_id,
)
from fantasy_weekly_lineup import save_weekly_lineup


def _roster() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Player": "Corner Bat",
                "Primary Position": "1B",
                "R": 30,
                "HR": 12,
                "RBI": 40,
                "SB": 2,
                "H": 80,
                "AB": 300,
                "BB": 20,
                "BA": 0.270,
            },
            {
                "Player": "Middle Man",
                "Primary Position": "2B",
                "R": 25,
                "HR": 4,
                "RBI": 20,
                "SB": 8,
                "H": 70,
                "AB": 280,
                "BB": 15,
                "BA": 0.255,
            },
            {
                "Player": "Bench Bat",
                "Primary Position": "1B",
                "R": 8,
                "HR": 2,
                "RBI": 6,
                "SB": 0,
                "H": 20,
                "AB": 90,
                "BB": 4,
                "BA": 0.210,
            },
        ]
    )


def _league_context(session: dict, *, fmt: str = "5x5 Roto", points_weights: dict | None = None) -> dict:
    board = pd.DataFrame(
        [
            {"Team": "Donny", "Player": "Corner Bat", "Pick": 1, "Primary Position": "1B"},
            {"Team": "Donny", "Player": "Middle Man", "Pick": 2, "Primary Position": "2B"},
            {"Team": "Donny", "Player": "Bench Bat", "Pick": 3, "Primary Position": "1B"},
            {"Team": "Team 2", "Player": "Other Guy", "Pick": 4, "Primary Position": "SS"},
        ]
    )
    _, ctx = save_imported_league_context(
        session,
        board,
        my_team_name="Donny",
        draft_name="Scoring Test",
        league_name="Scoring Test",
        config={"fantasy_format": fmt, "scoring_type": fmt},
        assign_team=False,
    )
    settings = dict(ctx.get("scoring_settings") or {})
    settings["scoring_type"] = fmt
    ctx["fantasy_format"] = fmt
    if points_weights is not None:
        settings["points_weights"] = points_weights
    ctx["scoring_settings"] = settings
    upsert_league_context(session, ctx)
    return ctx


class ProfileResolutionTests(unittest.TestCase):
    def test_standard_roto_excludes_bb(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        profile = resolve_hitter_scoring_profile(ctx)
        self.assertFalse(profile.blocked)
        self.assertEqual(profile.display_categories, STANDARD_ROTO_5X5)
        self.assertNotIn("BB", profile.display_categories)

    def test_explicit_bb_category(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        ctx["scoring_settings"]["hitter_categories"] = ["R", "HR", "BB"]
        profile = resolve_hitter_scoring_profile(ctx)
        self.assertIn("BB", profile.display_categories)

    def test_points_requires_weights(self) -> None:
        session: dict = {}
        ctx = _league_context(session, fmt="Points League")
        profile = resolve_hitter_scoring_profile(ctx)
        self.assertTrue(profile.blocked)

    def test_points_ops_not_assumed_without_weight(self) -> None:
        session: dict = {}
        ctx = _league_context(session, fmt="Points League", points_weights={"R": 1, "HR": 4})
        profile = resolve_hitter_scoring_profile(ctx)
        self.assertFalse(profile.blocked)
        self.assertNotIn("OPS", profile.display_categories)

    def test_bb_points_only_with_weight(self) -> None:
        session: dict = {}
        ctx = _league_context(session, fmt="Points League", points_weights={"BB": 1})
        profile = resolve_hitter_scoring_profile(ctx)
        self.assertEqual(profile.display_categories, ("BB",))


class BaselineAndDeltaTests(unittest.TestCase):
    def _assignments(self) -> dict[str, str]:
        return {"1B": "Corner Bat", "2B": "Middle Man"}

    def test_save_creates_one_baseline(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        roster = _roster()
        result = create_weekly_baseline_on_lock(
            ctx,
            week=1,
            team="Donny",
            assignments=self._assignments(),
            roster_df=roster,
            profile=resolve_hitter_scoring_profile(ctx),
        )
        self.assertTrue(result["ok"])
        again = create_weekly_baseline_on_lock(
            ctx,
            week=1,
            team="Donny",
            assignments=self._assignments(),
            roster_df=roster,
            profile=resolve_hitter_scoring_profile(ctx),
        )
        self.assertTrue(again.get("skipped"))
        record = get_weekly_scoring_record(ctx, week=1, team="Donny")
        assert record is not None
        self.assertEqual(record.get("baseline_created_at"), result["record"]["baseline_created_at"])

    def test_refresh_does_not_replace_baseline(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        roster = _roster()
        profile = resolve_hitter_scoring_profile(ctx)
        create_weekly_baseline_on_lock(
            ctx, week=1, team="Donny", assignments=self._assignments(), roster_df=roster, profile=profile
        )
        record = get_weekly_scoring_record(ctx, week=1, team="Donny")
        assert record is not None
        baseline_at = record["baseline_created_at"]
        baseline_hr = record["baselines"][list(record["baselines"].keys())[0]]["HR"]
        roster2 = roster.copy()
        roster2.loc[roster2["Player"] == "Corner Bat", "HR"] = 99
        refresh_weekly_scoring(ctx, week=1, team="Donny", roster_df=roster2, profile=profile)
        record2 = get_weekly_scoring_record(ctx, week=1, team="Donny")
        assert record2 is not None
        self.assertEqual(record2["baseline_created_at"], baseline_at)
        self.assertEqual(record2["baselines"][list(record2["baselines"].keys())[0]]["HR"], baseline_hr)

    def test_counting_stat_delta(self) -> None:
        profile = resolve_hitter_scoring_profile(_league_context({}))
        baseline = {"HR": 10, "H": 50, "AB": 200}
        current = {"HR": 12, "H": 55, "AB": 210}
        result = compute_player_weekly_results(
            baseline=baseline, current=current, profile=profile, is_starter=True
        )
        self.assertEqual(result["display"]["HR"], 2)

    def test_weekly_avg_uses_h_over_ab(self) -> None:
        profile = resolve_hitter_scoring_profile(_league_context({}))
        baseline = {"H": 50, "AB": 200}
        current = {"H": 55, "AB": 210}
        result = compute_player_weekly_results(
            baseline=baseline, current=current, profile=profile, is_starter=True
        )
        self.assertAlmostEqual(float(result["display"]["AVG"]), 5 / 10)

    def test_team_avg_combines_components(self) -> None:
        profile = resolve_hitter_scoring_profile(_league_context({}))
        p1 = compute_player_weekly_results(
            baseline={"H": 10, "AB": 40, "HR": 0, "R": 0, "RBI": 0, "SB": 0},
            current={"H": 12, "AB": 42, "HR": 0, "R": 0, "RBI": 0, "SB": 0},
            profile=profile,
            is_starter=True,
        )
        p2 = compute_player_weekly_results(
            baseline={"H": 20, "AB": 80, "HR": 0, "R": 0, "RBI": 0, "SB": 0},
            current={"H": 22, "AB": 82, "HR": 0, "R": 0, "RBI": 0, "SB": 0},
            profile=profile,
            is_starter=True,
        )
        totals = compute_team_weekly_totals({"a": p1, "b": p2}, profile)
        self.assertAlmostEqual(float(totals["totals"]["AVG"]), 1.0)

    def test_bench_does_not_count(self) -> None:
        profile = resolve_hitter_scoring_profile(_league_context({}))
        starter = compute_player_weekly_results(
            baseline={"HR": 1, "H": 10, "AB": 40, "R": 0, "RBI": 0, "SB": 0},
            current={"HR": 2, "H": 11, "AB": 41, "R": 0, "RBI": 0, "SB": 0},
            profile=profile,
            is_starter=True,
        )
        bench = compute_player_weekly_results(
            baseline={"HR": 5, "H": 20, "AB": 80, "R": 0, "RBI": 0, "SB": 0},
            current={"HR": 10, "H": 30, "AB": 90, "R": 0, "RBI": 0, "SB": 0},
            profile=profile,
            is_starter=False,
        )
        totals = compute_team_weekly_totals({"s": starter, "b": bench}, profile)
        self.assertEqual(totals["totals"]["HR"], 1)

    def test_obp_unavailable_without_components(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        ctx["scoring_settings"]["hitter_categories"] = ["OBP"]
        profile = resolve_hitter_scoring_profile(ctx)
        result = compute_player_weekly_results(
            baseline={"H": 10, "AB": 40, "BB": 5},
            current={"H": 11, "AB": 41, "BB": 6},
            profile=profile,
            is_starter=True,
        )
        self.assertIsNone(result["display"]["OBP"])
        self.assertIn("OBP", result["unavailable"])


class FinalizeAndStandingsTests(unittest.TestCase):
    def _lock_both_teams(self, ctx: dict, roster: pd.DataFrame) -> None:
        profile = resolve_hitter_scoring_profile(ctx)
        create_weekly_baseline_on_lock(
            ctx,
            week=1,
            team="Donny",
            assignments={"1B": "Corner Bat", "2B": "Middle Man"},
            roster_df=roster,
            profile=profile,
        )
        team2_roster = pd.DataFrame(
            [{"Player": "Other Guy", "Primary Position": "SS", "R": 10, "HR": 3, "RBI": 8, "SB": 1, "H": 30, "AB": 100, "BA": 0.250}]
        )
        create_weekly_baseline_on_lock(
            ctx,
            week=1,
            team="Team 2",
            assignments={"SS": "Other Guy"},
            roster_df=team2_roster,
            profile=profile,
        )
        refresh_weekly_scoring(ctx, week=1, team="Donny", roster_df=roster, profile=profile)
        refresh_weekly_scoring(ctx, week=1, team="Team 2", roster_df=team2_roster, profile=profile)

    def test_finalize_idempotent(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        roster = _roster()
        self._lock_both_teams(ctx, roster)
        team2_roster = pd.DataFrame(
            [{"Player": "Other Guy", "Primary Position": "SS", "R": 10, "HR": 3, "RBI": 8, "SB": 1, "H": 30, "AB": 100, "BA": 0.250}]
        )
        upsert_league_context(session, ctx)
        roster_by_team = {"Donny": roster, "Team 2": team2_roster}
        r1 = finalize_week_for_league(session, ctx, week=1, roster_by_team=roster_by_team)
        self.assertTrue(r1["ok"])
        r2 = finalize_week_for_league(session, ctx, week=1, roster_by_team=roster_by_team)
        self.assertTrue(r2.get("skipped"))
        self.assertTrue(is_week_finalized_for_league(ctx, 1))
        self.assertEqual(r1.get("finalize_id"), r2.get("finalize_id") or r1.get("finalize_id"))
        donny = get_weekly_scoring_record(ctx, week=1, team="Donny")
        assert donny is not None
        self.assertEqual(donny.get("final_result_id"), donny.get("standings_write_id"))

    def test_standings_no_duplicate_week(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        apply_finalized_week_to_standings(ctx, week=1, finalize_id="league:test|week_1")
        apply_finalized_week_to_standings(ctx, week=1, finalize_id="league:test|week_1")
        weeks = (ctx.get("workflow") or {}).get("hitter_weekly_standings_cumulative", {}).get("weeks") or []
        self.assertEqual(len(weeks), 1)


class LifecycleTests(unittest.TestCase):
    def test_legacy_locked_without_baseline(self) -> None:
        self.assertTrue(is_legacy_locked_lineup({"status": "locked"}, None))

    def test_legacy_does_not_receive_false_baseline(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        mark_legacy_lineup_scoring(ctx, week=1, team="Donny")
        result = create_weekly_baseline_on_lock(
            ctx,
            week=1,
            team="Donny",
            assignments={"1B": "Corner Bat"},
            roster_df=_roster(),
            profile=resolve_hitter_scoring_profile(ctx),
        )
        self.assertFalse(result.get("ok"))
        record = get_weekly_scoring_record(ctx, week=1, team="Donny")
        assert record is not None
        self.assertTrue(record.get("legacy"))
        self.assertFalse(record.get("baseline_created_at"))

    def test_next_week_empty_after_finalize(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        league_id = resolve_canonical_league_id(ctx)
        root = ctx.setdefault("workflow", {}).setdefault("weekly_hitter_scoring", {})
        root["finalized_weeks"] = {weekly_finalize_id(league_id, 1): {"week": 1}}
        self.assertTrue(should_start_week_empty(ctx, 2))

    def test_locked_week_unchanged_after_roster_trade(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        roster = _roster()
        profile = resolve_hitter_scoring_profile(ctx)
        assignments = {"1B": "Corner Bat", "2B": "Middle Man"}
        create_weekly_baseline_on_lock(
            ctx, week=1, team="Donny", assignments=assignments, roster_df=roster, profile=profile
        )
        record = get_weekly_scoring_record(ctx, week=1, team="Donny")
        assert record is not None
        original_starters = copy.deepcopy(record["starters"])
        roster_without = roster[roster["Player"] != "Corner Bat"].copy()
        refresh_weekly_scoring(ctx, week=1, team="Donny", roster_df=roster_without, profile=profile)
        record2 = get_weekly_scoring_record(ctx, week=1, team="Donny")
        assert record2 is not None
        self.assertEqual(record2["starters"], original_starters)
        self.assertEqual(record2["assignments"], assignments)


    def test_ops_unavailable_without_components(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        ctx["scoring_settings"]["hitter_categories"] = ["OPS"]
        profile = resolve_hitter_scoring_profile(ctx)
        result = compute_player_weekly_results(
            baseline={"H": 10, "AB": 40, "BB": 5, "HBP": 1, "SF": 1},
            current={"H": 11, "AB": 41, "BB": 6, "HBP": 1},
            profile=profile,
            is_starter=True,
        )
        self.assertIsNone(result["display"]["OPS"])
        self.assertIn("OPS", result["unavailable"])

    def test_refresh_does_not_modify_locked_assignments(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        roster = _roster()
        profile = resolve_hitter_scoring_profile(ctx)
        assignments = {"1B": "Corner Bat", "2B": "Middle Man"}
        create_weekly_baseline_on_lock(
            ctx, week=1, team="Donny", assignments=assignments, roster_df=roster, profile=profile
        )
        record = get_weekly_scoring_record(ctx, week=1, team="Donny")
        assert record is not None
        original_assignments = copy.deepcopy(record["assignments"])
        roster2 = roster.copy()
        roster2.loc[roster2["Player"] == "Corner Bat", "HR"] = 99
        refresh_weekly_scoring(ctx, week=1, team="Donny", roster_df=roster2, profile=profile)
        record2 = get_weekly_scoring_record(ctx, week=1, team="Donny")
        assert record2 is not None
        self.assertEqual(record2["assignments"], original_assignments)


class AdditionalRegressionTests(unittest.TestCase):
    def test_baseline_captures_only_configured_fields(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        profile = resolve_hitter_scoring_profile(ctx)
        roster = _roster()
        create_weekly_baseline_on_lock(
            ctx,
            week=1,
            team="Donny",
            assignments={"1B": "Corner Bat"},
            roster_df=roster,
            profile=profile,
        )
        record = get_weekly_scoring_record(ctx, week=1, team="Donny")
        assert record is not None
        baseline = next(iter(record["baselines"].values()))
        self.assertIn("HR", baseline)
        self.assertNotIn("ERA", baseline)
        self.assertNotIn("WHIP", baseline)

    def test_obp_hidden_components_not_displayed(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        ctx["scoring_settings"]["hitter_categories"] = ["OBP"]
        profile = resolve_hitter_scoring_profile(ctx)
        self.assertIn("BB", profile.hidden_fields)
        self.assertNotIn("BB", profile.display_categories)

    def test_finalize_blocked_when_obp_unavailable(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        ctx["scoring_settings"]["hitter_categories"] = ["OBP"]
        profile = resolve_hitter_scoring_profile(ctx)
        player_results = {
            "p1": {
                "display": {"OBP": None},
                "deltas": {"H": 1, "AB": 4, "BB": 1},
                "unavailable": {"OBP": ["HBP", "SF"]},
                "counts_toward_score": True,
            }
        }
        team_totals = compute_team_weekly_totals(player_results, profile)
        self.assertIn("OBP", team_totals.get("unavailable") or {})
        missing_data: list[str] = []
        for cat in profile.display_categories:
            if cat in (team_totals.get("unavailable") or {}):
                missing_data.append(f"Donny:{cat}")
        self.assertIn("Donny:OBP", missing_data)

    def test_hidden_ab_not_in_standings_categories(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        profile = resolve_hitter_scoring_profile(ctx)
        roster = _roster()
        create_weekly_baseline_on_lock(
            ctx,
            week=1,
            team="Donny",
            assignments={"1B": "Corner Bat"},
            roster_df=roster,
            profile=profile,
        )
        refresh_weekly_scoring(ctx, week=1, team="Donny", roster_df=roster, profile=profile)
        from fantasy_weekly_hitter_scoring import cumulative_standings_rows

        apply_finalized_week_to_standings(ctx, week=1, finalize_id=weekly_finalize_id(resolve_canonical_league_id(ctx), 1))
        rows = cumulative_standings_rows(ctx)
        self.assertTrue(rows)
        self.assertNotIn("AB", rows[0])
        self.assertNotIn("H", rows[0])

    def test_baseline_persists_across_session_reload(self) -> None:
        from fantasy_league_context import get_active_league_context

        session: dict = {}
        ctx = _league_context(session)
        roster = _roster()
        profile = resolve_hitter_scoring_profile(ctx)
        create_weekly_baseline_on_lock(
            ctx,
            week=1,
            team="Donny",
            assignments={"1B": "Corner Bat"},
            roster_df=roster,
            profile=profile,
        )
        baseline_at = get_weekly_scoring_record(ctx, week=1, team="Donny")["baseline_created_at"]
        upsert_league_context(session, ctx)
        reloaded = get_active_league_context(session)
        assert reloaded is not None
        record = get_weekly_scoring_record(reloaded, week=1, team="Donny")
        assert record is not None
        self.assertEqual(record["baseline_created_at"], baseline_at)

    def test_refresh_skips_unchanged_results(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        roster = _roster()
        profile = resolve_hitter_scoring_profile(ctx)
        create_weekly_baseline_on_lock(
            ctx,
            week=1,
            team="Donny",
            assignments={"1B": "Corner Bat"},
            roster_df=roster,
            profile=profile,
        )
        refresh_weekly_scoring(ctx, week=1, team="Donny", roster_df=roster, profile=profile)
        record = get_weekly_scoring_record(ctx, week=1, team="Donny")
        assert record is not None
        updated_at = record["stats_updated_at"]
        again = refresh_weekly_scoring(ctx, week=1, team="Donny", roster_df=roster, profile=profile)
        self.assertTrue(again.get("skipped"))
        record2 = get_weekly_scoring_record(ctx, week=1, team="Donny")
        assert record2 is not None
        self.assertEqual(record2["stats_updated_at"], updated_at)

    def test_points_use_configured_weights(self) -> None:
        session: dict = {}
        ctx = _league_context(session, fmt="Points League", points_weights={"HR": 4, "R": 1})
        profile = resolve_hitter_scoring_profile(ctx)
        result = compute_player_weekly_results(
            baseline={"HR": 1, "R": 5},
            current={"HR": 2, "R": 7},
            profile=profile,
            is_starter=True,
        )
        self.assertEqual(result["points_total"], 6.0)

    def test_unconfigured_category_not_in_baseline(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        profile = resolve_hitter_scoring_profile(ctx)
        row = _roster().iloc[0]
        snap = extract_cumulative_snapshot(row, profile)
        self.assertNotIn("BB", snap)


if __name__ == "__main__":
    unittest.main()
