"""Waiver recommendations know the roster and league rules; add/drop transactions are
validated, change ownership everywhere, and persist with the league."""

from __future__ import annotations

import unittest

import pandas as pd

from fantasy_actionable_recommendations import (
    build_actionable_position_weakness_note,
    build_team_actionable_summary,
    build_waiver_strategy_cards,
    league_strength_categories,
    league_weakness_categories,
)
from fantasy_league_context import (
    activate_archive_league_context,
    get_active_league_context,
    save_imported_league_context,
)
from fantasy_league_lineup_format import save_league_lineup_format
from fantasy_waiver_wire import (
    apply_waiver_move_pairs,
    build_waiver_pool,
    my_team_roster_dataframe,
    rostered_player_names,
)

STANDARD = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL"]
TEAM_1 = [
    ("Cal Raleigh", "C"), ("Pete Alonso", "1B"), ("Brandon Lowe", "2B"), ("Jose Ramirez", "3B"),
    ("Willy Adames", "SS"), ("James Wood", "OF"), ("Seiya Suzuki", "OF"), ("Randy Arozarena", "OF"),
    ("Jo Adell", "OF"), ("Michael Busch", "1B"),
]
TEAM_2 = [("Kyle Schwarber", "DH"), ("Aaron Judge", "OF")]


def _league(session: dict) -> dict:
    """Hitters-only imported league (no P slots), Team 1 claimed, standard lineup format."""
    rows, pick = [], 0
    for team, players in (("Team 1", TEAM_1), ("Team 2", TEAM_2)):
        for name, pos in players:
            pick += 1
            rows.append({"Pick": pick, "Round": 1, "Team": team, "Player": name, "Primary Position": pos})
    entry, _ctx = save_imported_league_context(
        session, pd.DataFrame(rows), my_team_name="Team 1", draft_name="QA", league_name="QA",
        save_only=True, assign_team=True,
    )
    activate_archive_league_context(session, entry["draft_id"])
    assert save_league_lineup_format(session, lineup_slots=STANDARD, roster_capacity=10)["ok"]
    return entry


POOL = pd.DataFrame(
    [
        {"Player": "Mike Trout", "Primary Position": "OF", "HR": 20, "RBI": 50, "R": 40, "SB": 2, "AB": 400},
        {"Player": "Victor Mederos", "Primary Position": "P", "HR": 0, "RBI": 2, "R": 0, "SB": 0, "AB": 3},
        {"Player": "Shohei Ohtani", "Primary Position": "TWP", "HR": 40, "RBI": 90, "R": 100, "SB": 20, "AB": 500},
        {"Player": "Jihwan Bae", "Primary Position": "OF", "HR": 1, "RBI": 8, "R": 15, "SB": 9, "AB": 120},
        {"Player": "Vimael Machin", "Primary Position": "SS", "HR": 3, "RBI": 12, "R": 10, "SB": 0, "AB": 150},
        {"Player": "Aaron Judge", "Primary Position": "OF", "HR": 40, "RBI": 100, "R": 90, "SB": 5, "AB": 500},
    ]
)


class HittersOnlyPoolTests(unittest.TestCase):
    def setUp(self):
        self.session: dict = {}
        _league(self.session)
        self.context = get_active_league_context(self.session)

    def test_pitcher_with_a_couple_of_rbi_is_not_a_waiver_hitter(self):
        names = set(build_waiver_pool(POOL, self.context)["Player"])
        self.assertNotIn("Victor Mederos", names)
        self.assertIn("Shohei Ohtani", names)  # two-way player stays
        self.assertNotIn("Aaron Judge", names)  # rostered by Team 2

    def test_only_incidental_hitting_marks_a_listed_pitcher(self):
        from fantasy_waiver_wire import _is_listed_pitcher_without_real_hitting as incidental

        self.assertTrue(incidental(pd.Series({"Primary Position": "P", "RBI": 2, "AB": 3})))
        self.assertFalse(incidental(pd.Series({"Primary Position": "P", "HR": 8, "AB": 180})))
        self.assertFalse(incidental(pd.Series({"Primary Position": "P", "Eligible Positions": "P, OF"})))
        self.assertFalse(incidental(pd.Series({"Primary Position": "TWP", "AB": 500})))


class LineupFillTests(unittest.TestCase):
    def test_utility_and_bench_take_spare_players(self):
        from fantasy_lineup_fill import unfilled_slots

        players = [["C"], ["1B"], ["OF"], ["OF"], ["3B"]]
        self.assertEqual(unfilled_slots(players, ["C", "1B", "OF", "OF", "DH"]), [])
        self.assertEqual(unfilled_slots(players, ["C", "1B", "OF", "OF", "DH", "BN"]), ["BN"])

    def test_one_player_fills_one_slot_and_specific_slots_win(self):
        from fantasy_lineup_fill import unfilled_slots

        # A lone SS/2B can cover SS or 2B, not both; UTIL cannot take a pitcher.
        self.assertEqual(len(unfilled_slots([["SS", "2B"]], ["SS", "2B"])), 1)
        self.assertEqual(unfilled_slots([["SS"], ["P"]], ["UTIL", "SS"]), ["UTIL"])
        self.assertEqual(unfilled_slots([["TWP"]], ["UTIL"]), [])

    def test_full_roster_has_no_open_utility_need(self):
        from fantasy_waiver_wire import compute_position_need_weights

        session: dict = {}
        _league(session)
        ctx = get_active_league_context(session)
        weights = compute_position_need_weights(ctx, my_team_roster_dataframe(ctx))
        self.assertEqual(set(weights.values()), {0.05})  # every slot, DH included, is covered


class CategoryStandingTests(unittest.TestCase):
    RANKS = {"HR": 3, "RBI": 1, "R": 1, "SB": 1, "AVG": 2}  # the QA league's snapshot

    def test_a_category_is_never_both_strength_and_weakness(self):
        strengths = league_strength_categories(self.RANKS, n_teams=4)
        weaknesses = league_weakness_categories(self.RANKS, n_teams=4)
        self.assertEqual(strengths, ["R", "RBI"])
        self.assertEqual(weaknesses, ["HR"])
        self.assertFalse(set(strengths) & set(weaknesses))

    def test_no_bottom_half_category_means_no_weakness(self):
        self.assertEqual(league_weakness_categories({"HR": 1, "SB": 2}, n_teams=4), [])

    def test_middle_rank_in_odd_league_is_neither(self):
        ranks = {"HR": 3}
        self.assertEqual(league_strength_categories(ranks, n_teams=5), [])
        self.assertEqual(league_weakness_categories(ranks, n_teams=5), [])

    def test_trade_line_never_trades_a_category_for_itself(self):
        lines = build_team_actionable_summary(strong_cats=["HR", "RBI"], weak_cats=["HR"], needs={}, waiver_pool=pd.DataFrame())
        trade = next(line for line in lines if "Best trade strategy" in line)
        self.assertIn("Trade excess **RBI** production for **HR**", trade)


class RosterAwareWaiverCardTests(unittest.TestCase):
    def setUp(self):
        self.session: dict = {}
        _league(self.session)
        self.context = get_active_league_context(self.session)
        self.roster = my_team_roster_dataframe(self.context)
        self.pool = build_waiver_pool(POOL, self.context)

    def test_full_roster_is_not_told_it_has_empty_spots(self):
        cards = build_waiver_strategy_cards(needs={}, waiver_pool=self.pool, league_context=self.context, my_roster=self.roster)
        self.assertTrue(cards)
        self.assertFalse([c for c in cards if "Fills an empty" in c["reason"]], cards)

    def test_without_the_roster_every_spot_looked_empty(self):
        cards = build_waiver_strategy_cards(needs={}, waiver_pool=self.pool, league_context=self.context)
        self.assertTrue(any("Fills an empty" in c["reason"] for c in cards))  # why the roster must be passed

    def test_weakest_position_option_must_play_there(self):
        starter = pd.DataFrame([{"Player": "Willy Adames", "Primary Position": "SS", "HR": 12, "RBI": 50, "R": 40, "SB": 8}])
        note = build_actionable_position_weakness_note(
            worst_pos="SS", worst_val=100, starter_df=starter, waiver_pool=self.pool, needs={},
            league_context=self.context, my_roster=self.roster,
        )
        self.assertIn("**Best Waiver Option:** Vimael Machin", note)
        self.assertIn("**Compared with Willy Adames (season totals):** HR −9 · RBI −38 · R −30", note)
        self.assertNotIn("Jihwan Bae", note)
        self.assertNotIn("Mederos", note)

    def test_no_eligible_option_says_so(self):
        note = build_actionable_position_weakness_note(
            worst_pos="C", worst_val=50, starter_df=pd.DataFrame([{"Player": "Cal Raleigh", "Primary Position": "C"}]),
            waiver_pool=self.pool, needs={}, league_context=self.context, my_roster=self.roster,
        )
        self.assertIn("none eligible at C", note)

    def test_numbered_outfield_and_utility_slots(self):
        starter = pd.DataFrame([{"Player": "Jo Adell", "Primary Position": "OF", "HR": 10, "RBI": 30, "R": 30, "SB": 3}])
        of_note = build_actionable_position_weakness_note(
            worst_pos="OF3", worst_val=70, starter_df=starter, waiver_pool=self.pool, needs={},
            league_context=self.context, my_roster=self.roster,
        )
        self.assertIn("**Best Waiver Option:**", of_note)
        self.assertNotIn("none eligible", of_note)
        util_note = build_actionable_position_weakness_note(
            worst_pos="UTIL", worst_val=70, starter_df=starter, waiver_pool=self.pool, needs={},
            league_context=self.context, my_roster=self.roster,
        )
        self.assertNotIn("none eligible", util_note)


class WaiverTransactionMatrixTests(unittest.TestCase):
    def setUp(self):
        self.session: dict = {}
        self.entry = _league(self.session)

    def _move(self, add: str, drop: str = "") -> dict:
        return apply_waiver_move_pairs(self.session, [{"add_player": add, "drop_player": drop}], stats_pool=POOL)

    def _team1(self) -> list[str]:
        ctx = get_active_league_context(self.session)
        return [p.get("player_name") for p in ctx["league_rosters"]["Team 1"]["players"]]

    def test_invalid_moves_change_nothing(self):
        before = self._team1()
        cases = {
            ("Aaron Judge", "Michael Busch"): "Aaron Judge is already rostered.",
            ("Shohei Ohtani", "Kyle Schwarber"): "Kyle Schwarber is not on your roster.",
            ("Michael Busch", "Michael Busch"): "Add and drop cannot be the same player: Michael Busch",
            ("Shohei Ohtani", ""): "Roster is full. Each add needs a matching drop.",
            ("Victor Mederos", "Michael Busch"): "Victor Mederos is a pitcher — this league has no pitcher roster spots.",
        }
        for (add, drop), error in cases.items():
            result = self._move(add, drop)
            self.assertFalse(result.get("ok"), (add, drop))
            self.assertEqual(result["errors"], [error])
        self.assertEqual(self._team1(), before)

    def test_valid_move_updates_every_view_and_persists_with_the_league(self):
        from draft_archive_state import get_draft_archive

        result = self._move("Mike Trout", "Jo Adell")
        self.assertTrue(result["ok"])
        ctx = get_active_league_context(self.session)
        self.assertIn("Mike Trout", self._team1())
        self.assertNotIn("Jo Adell", self._team1())
        self.assertEqual(ctx["ownership_map"]["mike trout"]["owner_team"], "Team 1")
        self.assertNotIn("jo adell", ctx["ownership_map"])
        roster_view = set(my_team_roster_dataframe(ctx)["Player"])  # Lineup / Trade read this
        self.assertIn("Mike Trout", roster_view)
        self.assertNotIn("Jo Adell", roster_view)
        self.assertIn("Jo Adell", set(build_waiver_pool(pd.DataFrame([{"Player": "Jo Adell", "Primary Position": "OF"}]), ctx)["Player"]))
        self.assertNotIn("Mike Trout", set(build_waiver_pool(POOL, ctx)["Player"]))
        activity = [(a["action"], a["player_name"]) for a in ctx["workflow"]["league_activity"]]
        self.assertEqual(activity[-2:], [("add", "Mike Trout"), ("drop", "Jo Adell")])
        self.assertEqual(ctx["roster_settings"]["lineup_format"]["lineup_slots"], STANDARD)
        archive = get_draft_archive(self.session, self.entry["draft_id"])
        archived = {p.get("player_name") for p in archive["league_rosters"]["Team 1"]["players"]}
        self.assertIn("Mike Trout", archived)  # Saved Draft Library copy follows the move
        self.assertNotIn("Jo Adell", archived)

    def test_dropping_the_only_catcher_is_allowed_with_a_warning(self):
        result = self._move("Shohei Ohtani", "Cal Raleigh")
        self.assertTrue(result["ok"])
        self.assertEqual(result["position_warnings"], ["Missing catcher"])

    def test_two_pairs_in_one_transaction(self):
        result = apply_waiver_move_pairs(
            self.session,
            [{"add_player": "Mike Trout", "drop_player": "Jo Adell"}, {"add_player": "Vimael Machin", "drop_player": "Michael Busch"}],
            stats_pool=POOL,
        )
        self.assertEqual(result["applied"], 2)
        self.assertEqual(len(self._team1()), 10)
        self.assertEqual(set(rostered_player_names(get_active_league_context(self.session))) & {"Jo Adell", "Michael Busch"}, set())


if __name__ == "__main__":
    unittest.main()


class SmallSampleRankingTests(unittest.TestCase):
    def test_full_season_hitter_outranks_a_hot_handful_of_at_bats(self):
        from fantasy_waiver_wire import recommend_adds_personalized

        session: dict = {}
        _league(session)
        ctx = get_active_league_context(session)
        pool = pd.DataFrame(
            [
                {"Player": "Call Up", "Primary Position": "OF", "AB": 4, "H": 2, "BA": 0.500, "HR": 0, "RBI": 0, "R": 1, "SB": 1},
                {"Player": "Yordan Alvarez", "Primary Position": "DH", "AB": 550, "H": 174, "BA": 0.316, "HR": 42, "RBI": 106, "R": 105, "SB": 1},
                {"Player": "Regular", "Primary Position": "OF", "AB": 520, "H": 140, "BA": 0.269, "HR": 20, "RBI": 70, "R": 75, "SB": 10},
            ]
        )
        adds = recommend_adds_personalized(
            build_waiver_pool(pool, ctx), {"targets": ["AVG"]}, context=ctx, my_roster=my_team_roster_dataframe(ctx), limit=3
        )
        self.assertEqual(list(adds["Player"])[0], "Yordan Alvarez")
        self.assertEqual(list(adds["Player"])[-1], "Call Up")

    def test_rate_stats_are_pulled_toward_the_pool_by_at_bats(self):
        from fantasy_waiver_wire import _shrink_rate_by_at_bats

        pool = pd.DataFrame({"AB": [4, 600], "BA": [0.500, 0.300]})
        shrunk = _shrink_rate_by_at_bats(pool, pool["BA"])
        pool_rate = (0.500 * 4 + 0.300 * 600) / 604
        self.assertAlmostEqual(shrunk[0], (0.500 * 4 + pool_rate * 200) / 204)
        self.assertLess(abs(shrunk[0] - pool_rate), 0.01)  # 2-for-4 lands near the pool, not at .500


def _names_only_league(session: dict) -> None:
    """Imported CSV with Pick/Round/Team/Player only — positions come from the stats feed."""
    rows = [{"Pick": i + 1, "Round": 1, "Team": "Team 1", "Player": n} for i, (n, _p) in enumerate(TEAM_1)]
    rows += [{"Pick": 20 + i, "Round": 1, "Team": "Team 2", "Player": n} for i, (n, _p) in enumerate(TEAM_2)]
    entry, _ctx = save_imported_league_context(
        session, pd.DataFrame(rows), my_team_name="Team 1", draft_name="QA", league_name="QA",
        save_only=True, assign_team=True,
    )
    activate_archive_league_context(session, entry["draft_id"])
    assert save_league_lineup_format(session, lineup_slots=STANDARD, roster_capacity=10)["ok"]


FEED = pd.concat(
    [
        pd.DataFrame([{"Player": "José Ramírez" if n == "Jose Ramirez" else n, "Primary Position": p, "AB": 500} for n, p in TEAM_1 + TEAM_2]),
        POOL[~POOL["Player"].isin(["Aaron Judge"])],
    ],
    ignore_index=True,
)


class NamesOnlyImportTests(unittest.TestCase):
    def test_move_does_not_report_positions_the_roster_still_has(self):
        session: dict = {}
        _names_only_league(session)
        result = apply_waiver_move_pairs(session, [{"add_player": "Vimael Machin", "drop_player": "Willy Adames"}], stats_pool=FEED)
        self.assertTrue(result["ok"])
        self.assertEqual(result["position_warnings"], [])  # was: Missing catcher, first baseman, ...

    def test_dropping_the_only_catcher_is_still_flagged(self):
        session: dict = {}
        _names_only_league(session)
        result = apply_waiver_move_pairs(session, [{"add_player": "Mike Trout", "drop_player": "Cal Raleigh"}], stats_pool=FEED)
        self.assertEqual(result["position_warnings"], ["Missing catcher"])


class PagesSeeTheMoveTests(unittest.TestCase):
    def test_workflow_descriptor_and_resolved_context_refresh_after_a_move(self):
        from fantasy_context_source import resolve_fantasy_workflow_source_descriptor
        from resolved_fantasy_context import resolve_fantasy_context_for_page

        session: dict = {}
        _names_only_league(session)
        resolve_fantasy_workflow_source_descriptor(session)  # warm both caches
        resolve_fantasy_context_for_page(session)
        apply_waiver_move_pairs(session, [{"add_player": "Mike Trout", "drop_player": "Jo Adell"}], stats_pool=FEED)
        desc_roster = str(resolve_fantasy_workflow_source_descriptor(session)["context"]["league_rosters"]["Team 1"])
        resolved_roster = str(resolve_fantasy_context_for_page(session).league_rosters["Team 1"])
        for roster in (desc_roster, resolved_roster):
            self.assertIn("Mike Trout", roster)
            self.assertNotIn("Jo Adell", roster)


class OneTimeLineupFlagsTests(unittest.TestCase):
    def test_flash_and_edit_mode_are_not_page_snapshotted(self):
        import page_state

        for key in ("lineup_format_saved_flash", "lineup_format_editing"):
            self.assertIn(key, page_state._PAGE_STATE_SKIP_KEYS)


class RosterStatsRebuildTests(unittest.TestCase):
    def test_names_only_rosters_take_positions_from_the_feed(self):
        from fantasy_league_context import build_roster_stats_from_league_context
        from player_name_normalization import normalize_player_name_for_merge

        session: dict = {}
        _names_only_league(session)
        apply_waiver_move_pairs(session, [{"add_player": "Mike Trout", "drop_player": "Jo Adell"}], stats_pool=FEED)
        rebuilt = build_roster_stats_from_league_context(
            get_active_league_context(session), FEED, normalize_name_fn=normalize_player_name_for_merge
        )
        team1 = rebuilt[rebuilt["Team"].astype(str) == "Team 1"].set_index("Player")
        self.assertEqual(team1.loc["Cal Raleigh", "Primary Position"], "C")
        self.assertEqual(team1.loc["Jose Ramirez", "Primary Position"], "3B")  # accent-folded match
        self.assertEqual(team1.loc["Mike Trout", "Primary Position"], "OF")
