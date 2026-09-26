"""Unit locks for human-test correction pass (prestart, badges, MLB team display)."""

from __future__ import annotations

import unittest

import pandas as pd


class TestPrestartInvariants(unittest.TestCase):
    def test_clears_deadline_and_board_on_not_started(self) -> None:
        from live_draft_ready_contract import enforce_prestart_invariants, prestart_expiration_blocked

        room = {
            "status": "not_started",
            "timer_deadline": 1_700_000_000.0,
            "timer_started_at": 1_699_999_940.0,
            "timer_live_ready_at": 1_699_999_940.0,
            "current_pick_index": 2,
            "draft_board": [{"fullName": "A"}, {"fullName": "B"}],
            "drafted_player_ids": ["1", "2"],
            "teams": ["Danny", "CPU"],
            "rosters": {"Danny": [{"fullName": "A"}], "CPU": [{"fullName": "B"}]},
            "pick_order": [
                {"Pick": 1, "Team": "Danny"},
                {"Pick": 2, "Team": "CPU"},
            ],
            "config": {"timer_seconds": 60, "your_team": "Danny", "picks_per_team": 3},
            "draft_room_id": "TESTROOM",
        }
        session: dict = {}
        out = enforce_prestart_invariants(room, session)
        self.assertTrue(out["ok"])
        self.assertTrue(out["cleared_timer"])
        self.assertTrue(out["reset_board"])
        self.assertTrue(out["reset_pick_index"])
        self.assertIsNone(room.get("timer_deadline"))
        self.assertIsNone(room.get("timer_started_at"))
        self.assertEqual(room.get("current_pick_index"), 0)
        self.assertEqual(room.get("draft_board"), [])
        self.assertTrue(prestart_expiration_blocked(room))

    def test_in_progress_not_mutated(self) -> None:
        from live_draft_ready_contract import enforce_prestart_invariants

        room = {
            "status": "in_progress",
            "timer_deadline": 1_700_000_060.0,
            "current_pick_index": 1,
            "draft_board": [{"fullName": "A"}],
        }
        out = enforce_prestart_invariants(room, {})
        self.assertTrue(out.get("skipped"))
        self.assertEqual(len(room["draft_board"]), 1)
        self.assertEqual(room["current_pick_index"], 1)


class TestBadgePoolRelative(unittest.TestCase):
    def test_naylor_26_hr_not_elite_when_pool_has_40plus(self) -> None:
        from live_draft_rec_badges import build_smart_recommendation_badges

        pool = pd.DataFrame(
            [
                {"fullName": "Aaron Judge", "Primary Position": "OF", "proj_HR": 55, "proj_RBI": 130, "proj_SB": 8, "proj_R": 120, "proj_AVG": 0.310, "Fantasy Edge": 0, "Model Rank": 2, "Market Rank": 2, "Expected Fantasy Value": 0.95},
                {"fullName": "Kyle Schwarber", "Primary Position": "OF", "proj_HR": 54, "proj_RBI": 110, "proj_SB": 5, "proj_R": 100, "proj_AVG": 0.220, "Fantasy Edge": 12, "Model Rank": 18, "Market Rank": 30, "Expected Fantasy Value": 0.80},
                {"fullName": "Matt Olson", "Primary Position": "1B", "proj_HR": 47, "proj_RBI": 115, "proj_SB": 1, "proj_R": 95, "proj_AVG": 0.250, "Fantasy Edge": 2, "Model Rank": 10, "Market Rank": 12, "Expected Fantasy Value": 0.82},
                {"fullName": "Juan Soto", "Primary Position": "OF", "proj_HR": 46, "proj_RBI": 105, "proj_SB": 12, "proj_R": 118, "proj_AVG": 0.290, "Fantasy Edge": 1, "Model Rank": 3, "Market Rank": 4, "Expected Fantasy Value": 0.92},
                {"fullName": "Pete Alonso", "Primary Position": "1B", "proj_HR": 44, "proj_RBI": 112, "proj_SB": 3, "proj_R": 90, "proj_AVG": 0.245, "Fantasy Edge": 0, "Model Rank": 14, "Market Rank": 14, "Expected Fantasy Value": 0.78},
                {"fullName": "Josh Naylor", "Primary Position": "1B", "proj_HR": 26, "proj_RBI": 102, "proj_SB": 18, "proj_R": 77, "proj_AVG": 0.281, "Fantasy Edge": 8, "Model Rank": 12, "Market Rank": 42, "Expected Fantasy Value": 0.75},
            ]
        )
        naylor = pool[pool["fullName"] == "Josh Naylor"].iloc[0]
        badges = build_smart_recommendation_badges(6, naylor, pool, gaps=["1B"], category_needs=["SB"])
        labels = [b[0] for b in badges]
        self.assertNotIn("Elite Power", labels)
        # Speed / RBI / bargain / fill are acceptable instead.
        self.assertTrue(
            any(
                x in labels
                for x in ("Speed Boost", "Speed at 1B", "Strong RBI", "Model Bargain", "Fills 1B Need", "Fills SB Need")
            ),
            msg=f"unexpected badges: {labels}",
        )

    def test_judge_elite_power_in_same_pool(self) -> None:
        from live_draft_rec_badges import build_smart_recommendation_badges

        pool = pd.DataFrame(
            [
                {"fullName": "Aaron Judge", "Primary Position": "OF", "proj_HR": 55, "proj_RBI": 131, "proj_SB": 8, "proj_R": 120, "proj_AVG": 0.310, "Fantasy Edge": 0, "Model Rank": 2, "Market Rank": 2, "Expected Fantasy Value": 0.95},
                {"fullName": "Josh Naylor", "Primary Position": "1B", "proj_HR": 26, "proj_RBI": 102, "proj_SB": 18, "proj_R": 77, "proj_AVG": 0.281, "Fantasy Edge": 8, "Model Rank": 12, "Market Rank": 42, "Expected Fantasy Value": 0.75},
                {"fullName": "B", "Primary Position": "OF", "proj_HR": 20, "proj_RBI": 70, "proj_SB": 5, "proj_R": 60, "proj_AVG": 0.250, "Fantasy Edge": 0, "Model Rank": 40, "Market Rank": 40, "Expected Fantasy Value": 0.5},
                {"fullName": "C", "Primary Position": "OF", "proj_HR": 18, "proj_RBI": 65, "proj_SB": 4, "proj_R": 55, "proj_AVG": 0.240, "Fantasy Edge": 0, "Model Rank": 50, "Market Rank": 50, "Expected Fantasy Value": 0.45},
            ]
        )
        judge = pool.iloc[0]
        badges = build_smart_recommendation_badges(1, judge, pool)
        labels = [b[0] for b in badges]
        self.assertIn("Elite Power", labels)


class TestMlbTeamDisplay(unittest.TestCase):
    def test_profile_card_prefers_mlb_team_over_fantasy(self) -> None:
        from player_photos import build_draft_profile_card_html

        row = pd.Series(
            {
                "fullName": "Cal Raleigh",
                "Primary Position": "C",
                "Team": "Danny",
                "Fantasy Team": "Danny",
                "MLB Team": "SEA",
                "proj_AVG": 0.241,
                "proj_HR": 52,
                "proj_RBI": 116,
                "proj_R": 102,
                "proj_SB": 10,
            }
        )
        html = build_draft_profile_card_html(row, {"url": "", "full_name": "Cal Raleigh"}, compact=True)
        self.assertIn("SEA", html)
        self.assertNotIn("C · Danny", html)
        self.assertNotIn(">Danny<", html)


class TestSortTieBreakers(unittest.TestCase):
    def test_market_rank_sort_monotonic(self) -> None:
        from live_draft_ux import sort_recommendation_table

        df = pd.DataFrame(
            [
                {"Player": "A", "Market Rank": 3, "Decision Score": 0.9, "Player Grade": 80},
                {"Player": "B", "Market Rank": 1, "Decision Score": 0.5, "Player Grade": 70},
                {"Player": "C", "Market Rank": 2, "Decision Score": 0.7, "Player Grade": 75},
            ]
        )
        out = sort_recommendation_table(df, "Market Rank")
        self.assertEqual(list(out["Market Rank"]), [1, 2, 3])

    def test_model_rank_sort_monotonic(self) -> None:
        from live_draft_ux import sort_recommendation_table

        df = pd.DataFrame(
            [
                {"Player": "A", "Model Rank": 5, "Decision Score": 0.9},
                {"Player": "B", "Model Rank": 2, "Decision Score": 0.5},
                {"Player": "C", "Model Rank": 2, "Decision Score": 0.8},
            ]
        )
        out = sort_recommendation_table(df, "Model Rank")
        self.assertEqual(list(out["Model Rank"]), [2, 2, 5])
        # Tie on Model Rank → higher Decision Score first.
        self.assertEqual(list(out["Player"][:2]), ["C", "B"])

    def test_player_grade_descending(self) -> None:
        from live_draft_ux import sort_recommendation_table

        df = pd.DataFrame(
            [
                {"Player": "A", "Player Grade": 70, "Decision Score": 0.9},
                {"Player": "B", "Player Grade": 90, "Decision Score": 0.5},
                {"Player": "C", "Player Grade": 80, "Decision Score": 0.7},
            ]
        )
        out = sort_recommendation_table(df, "Player Grade")
        self.assertEqual(list(out["Player Grade"]), [90, 80, 70])

    def test_decision_score_descending(self) -> None:
        from live_draft_ux import sort_recommendation_table

        df = pd.DataFrame(
            [
                {"Player": "A", "Decision Score": 0.4, "Player Grade": 90},
                {"Player": "B", "Decision Score": 0.9, "Player Grade": 70},
                {"Player": "C", "Decision Score": 0.7, "Player Grade": 80},
            ]
        )
        out = sort_recommendation_table(df, "Decision Score")
        self.assertEqual(list(out["Decision Score"]), [0.9, 0.7, 0.4])


class TestC1BAlonsoNeeds(unittest.TestCase):
    """C + 1B open → draft Alonso → only C remains eligible."""

    def _slots_c_1b(self) -> dict[str, int]:
        return {"C": 1, "1B": 1, "BN": 2}

    def _pool(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "playerID": "alonso",
                    "fullName": "Pete Alonso",
                    "Primary Position": "1B",
                    "Eligible Positions": "1B",
                    "Market Rank": 14,
                    "Model Rank": 14,
                    "Expected Fantasy Value": 0.78,
                    "Decision Score": 0.70,
                },
                {
                    "playerID": "raleigh",
                    "fullName": "Cal Raleigh",
                    "Primary Position": "C",
                    "Eligible Positions": "C",
                    "Market Rank": 25,
                    "Model Rank": 20,
                    "Expected Fantasy Value": 0.72,
                    "Decision Score": 0.68,
                },
                {
                    "playerID": "ohtani",
                    "fullName": "Shohei Ohtani",
                    "Primary Position": "DH",
                    "Eligible Positions": "DH,UTIL,SP",
                    "Market Rank": 1,
                    "Model Rank": 1,
                    "Expected Fantasy Value": 0.99,
                    "Decision Score": 0.95,
                },
                {
                    "playerID": "witt",
                    "fullName": "Bobby Witt",
                    "Primary Position": "SS",
                    "Eligible Positions": "SS",
                    "Market Rank": 3,
                    "Model Rank": 4,
                    "Expected Fantasy Value": 0.90,
                    "Decision Score": 0.88,
                },
                {
                    "playerID": "multi_c",
                    "fullName": "Multi C/1B",
                    "Primary Position": "C",
                    "Eligible Positions": "C,1B",
                    "Market Rank": 40,
                    "Model Rank": 35,
                    "Expected Fantasy Value": 0.55,
                    "Decision Score": 0.50,
                },
            ]
        )

    def test_before_pick_only_c_and_1b_eligible(self) -> None:
        from live_draft_roster_slots import (
            filter_candidates_to_team_open_positions,
            get_remaining_position_needs,
        )

        roster = pd.DataFrame()
        gaps = get_remaining_position_needs(roster, {"slots": self._slots_c_1b()})
        self.assertEqual(sorted(set(gaps)), ["1B", "C"])
        filtered = filter_candidates_to_team_open_positions(
            self._pool(), roster, config={"slots": self._slots_c_1b()}
        )
        names = set(filtered["fullName"].astype(str))
        self.assertIn("Pete Alonso", names)
        self.assertIn("Cal Raleigh", names)
        self.assertIn("Multi C/1B", names)
        self.assertNotIn("Shohei Ohtani", names)
        self.assertNotIn("Bobby Witt", names)

    def test_after_alonso_only_catchers_remain(self) -> None:
        from live_draft_roster_slots import (
            filter_candidates_to_team_open_positions,
            get_remaining_position_needs,
        )

        roster = pd.DataFrame(
            [{"fullName": "Pete Alonso", "Primary Position": "1B", "playerID": "alonso"}]
        )
        gaps = get_remaining_position_needs(roster, {"slots": self._slots_c_1b()})
        self.assertEqual(gaps, ["C"])
        filtered = filter_candidates_to_team_open_positions(
            self._pool(), roster, config={"slots": self._slots_c_1b()}
        )
        names = set(filtered["fullName"].astype(str))
        self.assertIn("Cal Raleigh", names)
        self.assertIn("Multi C/1B", names)
        self.assertNotIn("Pete Alonso", names)
        self.assertNotIn("Shohei Ohtani", names)
        self.assertNotIn("Bobby Witt", names)

    def test_after_catcher_starters_filled(self) -> None:
        from live_draft_roster_slots import get_remaining_position_needs

        roster = pd.DataFrame(
            [
                {"fullName": "Pete Alonso", "Primary Position": "1B", "playerID": "alonso"},
                {"fullName": "Cal Raleigh", "Primary Position": "C", "playerID": "raleigh"},
            ]
        )
        gaps = get_remaining_position_needs(roster, {"slots": self._slots_c_1b()})
        self.assertEqual(gaps, [])


class TestWhyRecommendedEvidence(unittest.TestCase):
    def test_naylor_why_is_specific_not_generic(self) -> None:
        from live_draft_room_ui import build_rec_card_why_bullets

        row = pd.Series(
            {
                "fullName": "Josh Naylor",
                "Primary Position": "1B",
                "proj_HR": 26,
                "proj_RBI": 102,
                "proj_R": 77,
                "proj_SB": 18,
                "proj_AVG": 0.281,
                "Model Rank": 12,
                "Market Rank": 42,
            }
        )
        bullets = build_rec_card_why_bullets(
            1,
            row,
            pd.DataFrame([row]),
            badges=[("Model Bargain", ""), ("Speed Boost", "")],
            gaps=["1B"],
            category_needs=["SB"],
        )
        text = " | ".join(bullets).lower()
        self.assertGreaterEqual(len(bullets), 2)
        self.assertNotIn("market value", text)
        self.assertNotIn("roster fit", text)
        self.assertTrue(
            any(k in text for k in ("sb", "stolen", "rbi", "hr", "bargain", "model")),
            msg=f"bullets={bullets}",
        )


class TestDraftAssistantLiveDraftParity(unittest.TestCase):
    def test_same_scoring_engine_top_names_align(self) -> None:
        from live_draft_pick_scoring import live_draft_target_counts, score_available_for_rule
        from live_draft_recommendations import live_draft_recommendations

        pool = pd.DataFrame(
            [
                {
                    "playerID": "a",
                    "fullName": "Catcher Ace",
                    "Primary Position": "C",
                    "Eligible Positions": "C",
                    "Market Rank": 80,
                    "Model Rank": 75,
                    "Expected Fantasy Value": 0.55,
                    "Decision Score": 0.50,
                    "Draft Fit Score": 0.9,
                    "Positional Fit": 0.95,
                    "Sleeper Score": 0.2,
                },
                {
                    "playerID": "b",
                    "fullName": "Shohei Ohtani",
                    "Primary Position": "DH",
                    "Eligible Positions": "DH,UTIL",
                    "Market Rank": 1,
                    "Model Rank": 1,
                    "Expected Fantasy Value": 0.99,
                    "Decision Score": 0.95,
                    "Draft Fit Score": 0.5,
                    "Positional Fit": 0.4,
                    "Sleeper Score": 0.1,
                },
                {
                    "playerID": "c",
                    "fullName": "OF Star",
                    "Primary Position": "OF",
                    "Eligible Positions": "OF",
                    "Market Rank": 5,
                    "Model Rank": 6,
                    "Expected Fantasy Value": 0.85,
                    "Decision Score": 0.80,
                    "Draft Fit Score": 0.6,
                    "Positional Fit": 0.5,
                    "Sleeper Score": 0.15,
                },
            ]
        )
        roster = pd.DataFrame(
            [
                {"playerID": "1b", "fullName": "1B", "Primary Position": "1B"},
                {"playerID": "2b", "fullName": "2B", "Primary Position": "2B"},
                {"playerID": "3b", "fullName": "3B", "Primary Position": "3B"},
                {"playerID": "ss", "fullName": "SS", "Primary Position": "SS"},
                {"playerID": "of1", "fullName": "OF1", "Primary Position": "OF"},
                {"playerID": "of2", "fullName": "OF2", "Primary Position": "OF"},
                {"playerID": "of3", "fullName": "OF3", "Primary Position": "OF"},
                {"playerID": "dh", "fullName": "DH", "Primary Position": "DH"},
                {"playerID": "p1", "fullName": "P1", "Primary Position": "SP"},
                {"playerID": "p2", "fullName": "P2", "Primary Position": "SP"},
            ]
        )
        slots = {
            "C": 1,
            "1B": 1,
            "2B": 1,
            "3B": 1,
            "SS": 1,
            "OF": 3,
            "DH": 1,
            "P": 2,
            "BN": 2,
        }
        cfg = {"slots": slots, "auto_pick_rule": "best market rank", "your_team": "Team A"}
        targets = live_draft_target_counts(cfg)
        scored, _ = score_available_for_rule(
            pool, roster, "best market rank", targets, config={**cfg, "room": None}
        )
        room = {
            "draft_room_id": "PARITY",
            "status": "in_progress",
            "current_pick_index": 0,
            "teams": ["Team A", "Team B"],
            "pick_order": [{"Pick": 1, "Round": 1, "Team": "Team A"}],
            "draft_board": [],
            "drafted_player_ids": [],
            "rosters": {"Team A": roster.to_dict("records"), "Team B": []},
            "config": cfg,
            "pool": pool,
        }
        top, *_ = live_draft_recommendations(room, top_n=3, session={})
        self.assertFalse(scored.empty)
        self.assertFalse(top.empty)
        self.assertEqual(
            str(scored.iloc[0].get("fullName") or ""),
            str(top.iloc[0].get("fullName") or ""),
        )
        self.assertEqual(str(top.iloc[0].get("Primary Position") or ""), "C")


class TestModelMarketIndependent(unittest.TestCase):
    def test_model_not_market_minus_one(self) -> None:
        from draft_scoring_pool import (
            POOL_KIND_VALID_PROJECTION,
            POOL_VALUE_KIND_KEY,
            ensure_draft_scoring_pool_columns_with_report,
        )

        pool = pd.DataFrame(
            [
                {
                    "fullName": f"P{i}",
                    "playerID": f"id{i}",
                    "Primary Position": "OF",
                    "Market Rank": 10 + i,
                    "Model Rank": 10 + i,
                    "Fantasy Edge": 0,
                    "Expected Fantasy Value": 0.5,
                    "Blended Projection Score": 100.0 - i * 7.5,
                }
                for i in range(12)
            ]
        )
        pool.attrs[POOL_VALUE_KIND_KEY] = POOL_KIND_VALID_PROJECTION
        out, _report = ensure_draft_scoring_pool_columns_with_report(pool)
        model = pd.to_numeric(out["Model Rank"], errors="coerce")
        market = pd.to_numeric(out["Market Rank"], errors="coerce")
        # Mechanical Market-1 pattern must not dominate.
        mech = int(((model == (market - 1)).fillna(False)).sum())
        self.assertLess(mech, len(out) // 2)
        differ = int((model != market).fillna(False).sum())
        self.assertGreaterEqual(differ, 8)


if __name__ == "__main__":
    unittest.main()
